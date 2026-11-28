"""CV Content Generator + deterministic assembly that enforces the facts."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.prompts import load_prompt, untrusted
from app.providers.llm import LLMError, get_llm
from app.schemas.cv import ParsedCV
from app.schemas.resume import (
    GeneratedContent,
    PortfolioLink,
    ResumeCandidate,
    ResumeCertification,
    ResumeDocument,
    ResumeEducation,
    ResumeExperience,
    ResumeLanguage,
    ResumeProject,
    StructurePlan,
)
from app.services.cv.facts import edu_id, exp_id, facts_payload, facts_text
from app.services.cv.profile_service import normalize_skill
from app.services.cv.structure import plan_structure

logger = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

SUMMARY_TEMPLATES = {
    "en": ("{title} with {exp} of experience{field}.", "Skilled in {skills}.", "Seeking a role as {target}."),
    "de": ("{title} mit {exp} Berufserfahrung{field}.", "Kenntnisse in {skills}.", "Angestrebte Position: {target}."),
    "ru": ("{title}, опыт работы — {exp}{field}.", "Владею: {skills}.", "Ищу позицию: {target}."),
    "uk": ("{title}, досвід роботи — {exp}{field}.", "Володію: {skills}.", "Шукаю позицію: {target}."),
}
EXP_UNITS = {
    "en": ("less than a year", "{n} year", "{n} years"),
    "de": ("weniger als einem Jahr", "{n} Jahr", "{n} Jahren"),
    "ru": ("менее года", "{n} год", "{n} лет"),
    "uk": ("менше року", "{n} рік", "{n} років"),
}
FIELD_JOIN = {"en": " in {f}", "de": " im Bereich {f}", "ru": " в сфере {f}", "uk": " у сфері {f}"}
ENTRY_SUMMARY = {
    "en": "Motivated candidate starting a career{target_part}.",
    "de": "Motivierte/r Berufseinsteiger/in{target_part}.",
    "ru": "Начинающий специалист{target_part}.",
    "uk": "Початківець-фахівець{target_part}.",
}
TARGET_PART = {"en": " as {t}", "de": " als {t}", "ru": " — {t}", "uk": " — {t}"}


def _years_text(lang: str, months: int) -> str:
    units = EXP_UNITS.get(lang, EXP_UNITS["en"])
    if months < 12:
        return units[0]
    n = months // 12
    if lang in ("ru", "uk"):
        from app.services.i18n import plural_form

        form = plural_form(lang, n)
        word = {"ru": {"one": "{n} год", "few": "{n} года", "many": "{n} лет"},
                "uk": {"one": "{n} рік", "few": "{n} роки", "many": "{n} років"}}[lang][form]
        return word.format(n=n)
    return (units[1] if n == 1 else units[2]).format(n=n)


def deterministic_summary(facts: ParsedCV, target_roles: list[str], lang: str) -> str:
    """Summary composed only of facts (fallback and MOCK_MODE)."""
    lang = lang if lang in SUMMARY_TEMPLATES else "en"
    target = ", ".join(target_roles[:2])
    title = (facts.experience[0].job_title if facts.experience else None) or facts.primary_field
    skills = [*facts.skills.software, *facts.skills.hard, *facts.skills.tools][:5]
    months = facts.total_experience_months or 0
    if not facts.experience or not title:
        part = TARGET_PART[lang].format(t=target) if target else ""
        text = ENTRY_SUMMARY[lang].format(target_part=part)
        if skills:
            text += " " + SUMMARY_TEMPLATES[lang][1].format(skills=", ".join(skills))
        return text
    t1, t2, t3 = SUMMARY_TEMPLATES[lang]
    field = FIELD_JOIN[lang].format(f=facts.primary_field) if facts.primary_field and facts.primary_field != title else ""
    parts = [t1.format(title=title, exp=_years_text(lang, months), field=field)]
    if skills:
        parts.append(t2.format(skills=", ".join(skills)))
    if target and target.lower() != title.lower():
        parts.append(t3.format(target=target))
    return " ".join(parts)


def _clean_bullet(text: str) -> str:
    text = re.sub(r"^[•\-*·▪●\s]+", "", text).strip().rstrip(".;")
    return text[:1].upper() + text[1:] if text else text


def _numbers_grounded(text: str, source: str, allowed: set[str]) -> bool:
    for num in NUMBER_RE.findall(text):
        if num in allowed:
            continue
        if num not in source and num.replace(",", ".") not in source and num.replace(".", ",") not in source:
            return False
    return True


def _filter_known(items: list[str], known: dict[str, str]) -> list[str]:
    """Keep only skills that exist in the facts (returns the generated spelling)."""
    out: list[str] = []
    for item in items:
        key = normalize_skill(item)
        if key in known or any(key in k or k in key for k in known if len(k) > 3 and len(key) > 3):
            if item not in out:
                out.append(item)
    return out


def assemble_document(
    facts: ParsedCV,
    plan: StructurePlan,
    content: GeneratedContent | None,
    *,
    template: str,
    language: str,
    target_roles: list[str],
    page_limit: int | None = None,
    extra: dict[str, Any] | None = None,
) -> ResumeDocument:
    source = facts_text(facts, extra)
    years = str((facts.total_experience_months or 0) // 12)
    allowed_numbers = {years}
    gen_exp = {g.id: g for g in (content.experience if content else [])}
    gen_edu = {g.id: g for g in (content.education if content else [])}
    rejected = 0

    def build_exp(i: int) -> ResumeExperience:
        nonlocal rejected
        e = facts.experience[i]
        eid = exp_id(i)
        original = [_clean_bullet(b) for b in [*e.achievements, *e.responsibilities] if b.strip()]
        bullets = []
        for b in (gen_exp[eid].bullets if eid in gen_exp else []):
            b = _clean_bullet(b)
            if b and _numbers_grounded(b, source, allowed_numbers):
                bullets.append(b)
            else:
                rejected += 1
        if not bullets:
            bullets = original
        if page_limit == 1:
            bullets = bullets[:3]
        return ResumeExperience(
            id=eid, company=e.company, job_title=e.job_title, location=e.location,
            start_date=e.start_date, end_date=e.end_date, is_current=e.is_current,
            employment_type=e.employment_type, bullets=bullets[:6], tools=e.tools,
        )

    index = {exp_id(i): i for i in range(len(facts.experience))}
    experience = [build_exp(index[i]) for i in plan.relevant_experience_ids if i in index]
    additional = [build_exp(index[i]) for i in plan.additional_experience_ids if i in index]
    # Reverse-chronological inside sections (current first, then by start date).
    def chrono_key(x: ResumeExperience) -> tuple[int, str]:
        return (1 if x.is_current else 0, x.end_date or x.start_date or "")
    experience.sort(key=chrono_key, reverse=True)
    additional.sort(key=chrono_key, reverse=True)

    education = []
    for i, e in enumerate(facts.education):
        g = gen_edu.get(edu_id(i))
        details = [d for d in (g.details if g else []) if _numbers_grounded(d, source, allowed_numbers)]
        education.append(ResumeEducation(
            id=edu_id(i), institution=e.institution, degree=e.degree, specialization=e.specialization,
            start_date=e.start_date, end_date=e.end_date, status=e.status, details=details[:3],
        ))
    education.sort(key=lambda x: x.end_date or x.start_date or "", reverse=True)

    known = {normalize_skill(s): s for s in [*facts.skills.all(), *[t for e in facts.experience for t in e.tools]]}
    hard_facts = [*facts.skills.hard, *facts.skills.technical]
    software_facts = [*facts.skills.software, *facts.skills.tools]
    skills = _filter_known(content.skills, known) if content else []
    software = _filter_known(content.software, known) if content else []
    soft = _filter_known(content.soft_skills, known) if content else []
    transferable = _filter_known(content.transferable_skills, known) if content else []
    skills = skills or hard_facts
    software = software or software_facts
    soft = soft or list(facts.skills.soft)
    if plan.profile_type == "career_change" and not transferable:
        transferable = [*hard_facts, *facts.skills.soft][:8]

    summary = content.professional_summary if content else None
    if not summary or not _numbers_grounded(summary, source, allowed_numbers):
        if summary:
            rejected += 1
        summary = deterministic_summary(facts, target_roles, language)
    achievements = [
        a for a in (content.achievements if content else []) if _numbers_grounded(a, source, allowed_numbers)
    ] or [a for e in facts.experience for a in e.achievements][:5]

    gen_projects = {p.name.lower(): p for p in (content.projects if content else [])}
    projects = []
    for p in facts.projects:
        g = gen_projects.get(p.name.lower())
        desc = g.description if g and g.description and _numbers_grounded(g.description, source, allowed_numbers) else p.description
        projects.append(ResumeProject(name=p.name, description=desc, role=p.role, url=p.url, technologies=p.technologies))

    c = facts.candidate
    portfolio_urls = [u for u in [c.portfolio_url, *c.other_links] if u]
    if rejected:
        logger.info("content generator: %s ungrounded fragments replaced", rejected)
    headline = content.headline if content and content.headline else (target_roles[0] if target_roles else None)
    if headline and not _numbers_grounded(headline, source, allowed_numbers):
        headline = None
    return ResumeDocument(
        candidate=ResumeCandidate(
            full_name=c.full_name or "",
            headline=headline,
            email=c.email,
            phone=c.phone,
            location=", ".join(x for x in (c.city, c.country) if x) or None,
            linkedin_url=c.linkedin_url,
            portfolio_url=c.portfolio_url,
            other_links=c.other_links,
        ),
        target_roles=target_roles,
        professional_summary=summary,
        experience=experience,
        additional_experience=additional,
        achievements=achievements if "achievements" in plan.section_order else [],
        skills=skills,
        soft_skills=soft,
        software=software,
        transferable_skills=transferable if plan.profile_type == "career_change" else [],
        education=education,
        languages=[ResumeLanguage(language=x.language, level=x.level) for x in facts.languages],
        projects=projects,
        certifications=[ResumeCertification(**x.model_dump()) for x in facts.certifications],
        portfolio=[PortfolioLink(url=u) for u in portfolio_urls] if "portfolio" in plan.section_order else [],
        section_order=plan.section_order,
        template=template,  # type: ignore[arg-type]
        document_language=language,
        page_limit=page_limit,
    )


async def generate_content(
    facts: ParsedCV,
    plan: StructurePlan,
    *,
    language: str,
    target_roles: list[str],
    instructions: list[str] | None = None,
    page_limit: int | None = None,
    extra: dict[str, Any] | None = None,
) -> GeneratedContent | None:
    request = {
        "document_language": language,
        "target_roles": target_roles,
        "profile_type": plan.profile_type,
        "section_order": plan.section_order,
        "relevant_experience_ids": plan.relevant_experience_ids,
        "page_budget": page_limit or plan.target_pages,
        "user_edit_instructions": instructions or [],
    }
    try:
        return await get_llm().generate_json(
            task="cv_content_generator",
            system=load_prompt("cv_content_generator"),
            user="Write the CV content.\n" + untrusted("candidate_facts", facts_payload(facts, extra))
            + "\n" + untrusted("request", request),
            schema=GeneratedContent,
            context={"facts": facts, "language": language, "target_roles": target_roles,
                     "instructions": instructions or [], "page_limit": page_limit},
            temperature=0.4,
        )
    except LLMError:
        logger.warning("content generator unavailable; using facts verbatim")
        return None


async def generate_resume(
    facts: ParsedCV,
    *,
    target_roles: list[str],
    language: str,
    template: str | None = None,
    direction: str | None = None,
    instructions: list[str] | None = None,
    page_limit: int | None = None,
    plan: StructurePlan | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[ResumeDocument, StructurePlan]:
    plan = plan or await plan_structure(facts, target_roles, direction)
    content = await generate_content(
        facts, plan, language=language, target_roles=target_roles, instructions=instructions,
        page_limit=page_limit, extra=extra,
    )
    doc = assemble_document(
        facts, plan, content, template=template or plan.recommended_template, language=language,
        target_roles=target_roles, page_limit=page_limit, extra=extra,
    )
    return doc, plan
