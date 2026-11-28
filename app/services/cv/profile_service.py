"""Applying structured CV data to the candidate profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CandidateLanguage,
    CandidateProfile,
    CandidateSkill,
    EducationRecord,
    Portfolio,
    WorkExperience,
)
from app.database.models.enums import SkillCategory
from app.database.repositories.profiles import ProfileRepository
from app.schemas.cv import ParsedCV

_SKILL_FIELDS = {
    "hard": SkillCategory.HARD,
    "soft": SkillCategory.SOFT,
    "software": SkillCategory.SOFTWARE,
    "tools": SkillCategory.TOOL,
    "technical": SkillCategory.TECHNICAL,
}


def normalize_skill(name: str) -> str:
    return " ".join(name.lower().split())[:120]


async def apply_parsed_cv(
    session: AsyncSession, user_id: int, parsed: ParsedCV, source: str
) -> CandidateProfile:
    """Replace CV-derived sections of the profile with ``parsed``.

    User-entered skills (source="user") are preserved. Scalar fields are only
    overwritten with non-empty values so manual edits are not wiped by a
    worse document.
    """
    repo = ProfileRepository(session)
    profile = await repo.get_or_create(user_id)
    c = parsed.candidate
    for attr, value in (
        ("full_name", c.full_name),
        ("email", c.email),
        ("phone", c.phone),
        ("city", c.city),
        ("country", c.country),
        ("linkedin_url", c.linkedin_url),
        ("portfolio_url", c.portfolio_url),
        ("headline", parsed.headline),
        ("summary", parsed.summary),
        ("primary_field", parsed.primary_field),
    ):
        if value:
            setattr(profile, attr, value)
    profile.total_experience_months = parsed.total_experience_months
    profile.has_no_experience = not parsed.experience
    profile.certifications = [x.model_dump() for x in parsed.certifications]
    profile.projects = [x.model_dump() for x in parsed.projects]
    profile.source = source
    profile.confirmed_at = None

    profile.experiences.clear()
    for pos, exp in enumerate(parsed.experience):
        profile.experiences.append(
            WorkExperience(
                company=exp.company,
                job_title=exp.job_title,
                location=exp.location,
                start_date=exp.start_date,
                end_date=exp.end_date,
                is_current=exp.is_current,
                employment_type=exp.employment_type,
                responsibilities=exp.responsibilities,
                achievements=exp.achievements,
                tools=exp.tools,
                position=pos,
            )
        )

    profile.education.clear()
    for pos, edu in enumerate(parsed.education):
        profile.education.append(
            EducationRecord(
                institution=edu.institution,
                degree=edu.degree,
                specialization=edu.specialization,
                start_date=edu.start_date,
                end_date=edu.end_date,
                status=edu.status,
                position=pos,
            )
        )

    # Reuse existing rows: the unit of work inserts before it deletes, so replacing
    # a row with an identical (category, name) would violate the unique constraint.
    wanted: dict[tuple[str, str], str] = {}
    for attr, category in _SKILL_FIELDS.items():
        for name in getattr(parsed.skills, attr):
            wanted.setdefault((category.value, normalize_skill(name)), name[:120])
    keep = []
    for skill in profile.skills:
        key = (skill.category, skill.name_normalized)
        if skill.source == "user" or key in wanted:
            keep.append(skill)
            wanted.pop(key, None)
    profile.skills[:] = keep
    for (category, key), name in wanted.items():
        profile.skills.append(CandidateSkill(name=name, name_normalized=key, category=category, source="cv"))

    by_lang = {lang.language.lower(): lang for lang in profile.languages}
    for item in parsed.languages:
        current = by_lang.get(item.language.lower())
        if current is None:
            profile.languages.append(CandidateLanguage(language=item.language, level=item.level))
        elif item.level != "Unknown":
            current.level = item.level

    urls = {p.url for p in profile.portfolios}
    for url in [c.portfolio_url, *c.other_links]:
        if url and url not in urls:
            urls.add(url)
            profile.portfolios.append(Portfolio(url=url, kind="portfolio" if url == c.portfolio_url else "link"))

    await session.flush()
    return profile


@dataclass(slots=True)
class ProfileSummary:
    full_name: str | None
    primary_field: str | None
    experience_months: int | None
    has_no_experience: bool
    languages: list[tuple[str, str]] = field(default_factory=list)
    software: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    last_job: str | None = None


def summarize_profile(profile: CandidateProfile) -> ProfileSummary:
    last = profile.experiences[0] if profile.experiences else None
    location = ", ".join(x for x in (profile.city, profile.country) if x) or None
    return ProfileSummary(
        full_name=profile.full_name,
        primary_field=profile.primary_field or (last.job_title if last else None),
        experience_months=profile.total_experience_months,
        has_no_experience=profile.has_no_experience,
        languages=[(lang.language, lang.level) for lang in profile.languages],
        software=[s.name for s in profile.skills if s.category in ("software", "tool")][:12],
        skills=[s.name for s in profile.skills if s.category in ("hard", "technical")][:12],
        email=profile.email,
        phone=profile.phone,
        location=location,
        last_job=" — ".join(x for x in (last.job_title, last.company) if x) if last else None,
    )


async def confirm_profile(profile: CandidateProfile) -> None:
    profile.confirmed_at = datetime.now(UTC)
