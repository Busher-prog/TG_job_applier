"""Candidate facts: the single source of truth that AI agents may rephrase but never change."""

from __future__ import annotations

import re
from typing import Any

from app.database.models import CandidateProfile
from app.schemas.cv import (
    CandidateContact,
    CertificationItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    ParsedCV,
    ProjectItem,
    SkillsBlock,
)


def profile_to_facts(profile: CandidateProfile) -> ParsedCV:
    skills = SkillsBlock()
    mapping = {"hard": "hard", "soft": "soft", "software": "software", "tool": "tools", "technical": "technical"}
    for s in profile.skills:
        getattr(skills, mapping.get(s.category, "hard")).append(s.name)
    return ParsedCV(
        candidate=CandidateContact(
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            city=profile.city,
            country=profile.country,
            linkedin_url=profile.linkedin_url,
            portfolio_url=profile.portfolio_url,
            other_links=[p.url for p in profile.portfolios if p.url != profile.portfolio_url],
        ),
        headline=profile.headline,
        summary=profile.summary,
        primary_field=profile.primary_field,
        total_experience_months=profile.total_experience_months,
        experience=[
            ExperienceItem(
                company=e.company, job_title=e.job_title, location=e.location,
                start_date=e.start_date, end_date=e.end_date, is_current=e.is_current,
                employment_type=e.employment_type, responsibilities=e.responsibilities,
                achievements=e.achievements, tools=e.tools,
            )
            for e in profile.experiences
        ],
        education=[
            EducationItem(
                institution=e.institution, degree=e.degree, specialization=e.specialization,
                start_date=e.start_date, end_date=e.end_date, status=e.status or "unknown",
            )
            for e in profile.education
        ],
        skills=skills,
        languages=[LanguageItem(language=lang.language, level=lang.level) for lang in profile.languages],
        certifications=[CertificationItem.model_validate(c) for c in profile.certifications or []],
        projects=[ProjectItem.model_validate(p) for p in profile.projects or []],
    )


def exp_id(index: int) -> str:
    return f"exp{index + 1}"


def edu_id(index: int) -> str:
    return f"edu{index + 1}"


def facts_payload(facts: ParsedCV, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Facts with stable ids, as given to AI agents."""
    data = facts.model_dump(exclude={"warnings", "detected_language"})
    for i, item in enumerate(data["experience"]):
        item["id"] = exp_id(i)
    for i, item in enumerate(data["education"]):
        item["id"] = edu_id(i)
    if extra:
        data["additional_facts"] = extra
    return data


def facts_text(facts: ParsedCV, extra: dict[str, Any] | None = None) -> str:
    """Flattened text of every fact, used to verify that generated text adds no new numbers."""
    import json

    return json.dumps(facts_payload(facts, extra), ensure_ascii=False).lower()


_TOKEN = re.compile(r"[\wäöüß]+", re.I)
_STOP = {"and", "the", "of", "for", "in", "und", "der", "die", "das", "и", "в", "та", "з", "junior", "senior",
         "assistant", "manager", "specialist", "lead", "head", "intern"}


def tokens(text: str | None) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if len(t) > 2 and t.lower() not in _STOP}
