"""CV Structure Planner (AI) with a deterministic rule-based fallback."""

from __future__ import annotations

import logging
from typing import Any

from app.prompts import load_prompt, untrusted
from app.providers.llm import LLMError, get_llm
from app.schemas.cv import ParsedCV
from app.schemas.resume import StructurePlan
from app.services.cv.facts import exp_id, facts_payload, tokens

logger = logging.getLogger(__name__)

CREATIVE_HINTS = {
    "video", "editor", "design", "designer", "photographer", "photo", "content", "creator", "motion",
    "animator", "illustrator", "artist", "creative", "ux", "ui", "art", "videographer", "монтажер",
    "дизайнер", "видео", "відео", "фотограф", "контент", "cutter", "grafik", "grafikdesigner",
}


def _is_creative(roles: list[str], facts: ParsedCV) -> bool:
    words = set()
    for r in roles:
        words |= tokens(r)
    if not roles:
        words |= tokens(facts.primary_field)
        for e in facts.experience[:2]:
            words |= tokens(e.job_title)
    return bool(words & CREATIVE_HINTS)


def _experience_relevance(facts: ParsedCV, roles: list[str]) -> tuple[list[str], list[str]]:
    if not roles:
        return [exp_id(i) for i in range(len(facts.experience))], []
    target = set().union(*(tokens(r) for r in roles))
    relevant, other = [], []
    for i, e in enumerate(facts.experience):
        words = tokens(e.job_title) | tokens(" ".join(e.responsibilities + e.achievements + e.tools))
        (relevant if words & target else other).append(exp_id(i))
    return relevant, other


def rule_based_plan(facts: ParsedCV, target_roles: list[str], direction: str | None = None) -> StructurePlan:
    months = facts.total_experience_months or 0
    studying = any(e.status == "in_progress" for e in facts.education)
    relevant, other = _experience_relevance(facts, target_roles)
    creative = _is_creative(target_roles, facts)
    has_portfolio = bool(facts.candidate.portfolio_url or facts.candidate.other_links)

    if direction == "change" or (target_roles and facts.experience and not relevant and months >= 12):
        ptype = "career_change"
        order = ["professional_summary", "transferable_skills", "projects", "experience",
                 "additional_experience", "skills", "education", "certifications", "languages"]
    elif creative and (has_portfolio or facts.projects):
        ptype = "creative"
        order = ["professional_summary", "portfolio", "experience", "projects", "software", "skills",
                 "education", "certifications", "languages"]
        relevant, other = relevant + other, []
    elif studying or months < 12:
        ptype = "student" if studying or facts.education else "entry_level"
        order = ["professional_summary", "education", "skills", "projects", "experience", "certifications",
                 "software", "languages"]
        relevant, other = relevant + other, []
    else:
        ptype = "experienced"
        order = ["professional_summary", "experience", "achievements", "skills", "software", "education",
                 "certifications", "projects", "languages"]
        relevant, other = relevant + other, []

    if ptype != "career_change":
        order = [s for s in order if s != "additional_experience"]
    template = "creative" if ptype == "creative" else "classic_ats"
    return StructurePlan(
        profile_type=ptype,  # type: ignore[arg-type]
        section_order=order,  # type: ignore[arg-type]
        relevant_experience_ids=relevant,
        additional_experience_ids=other,
        recommended_template=template,  # type: ignore[arg-type]
        target_pages=2 if months > 96 else 1,
        rationale="rule_based",
    )


def sanitize_plan(plan: StructurePlan, facts: ParsedCV) -> StructurePlan:
    """Make the plan consistent with the facts: every experience entry placed exactly once."""
    valid = [exp_id(i) for i in range(len(facts.experience))]
    relevant = [i for i in dict.fromkeys(plan.relevant_experience_ids) if i in valid]
    additional = [i for i in dict.fromkeys(plan.additional_experience_ids) if i in valid and i not in relevant]
    missing = [i for i in valid if i not in relevant and i not in additional]
    relevant += missing  # never drop an employer
    if not relevant and additional:
        relevant, additional = additional, []
    plan.relevant_experience_ids = relevant
    plan.additional_experience_ids = additional
    if additional and "additional_experience" not in plan.section_order:
        plan.section_order.append("additional_experience")
    if "experience" not in plan.section_order and relevant:
        plan.section_order.insert(1, "experience")
    return plan


async def plan_structure(facts: ParsedCV, target_roles: list[str], direction: str | None = None) -> StructurePlan:
    payload: dict[str, Any] = {"target_roles": target_roles, "career_direction": direction}
    try:
        plan = await get_llm().generate_json(
            task="cv_structure_planner",
            system=load_prompt("cv_structure_planner"),
            user="Plan the CV structure.\n" + untrusted("candidate_facts", facts_payload(facts))
            + "\n" + untrusted("targets", payload),
            schema=StructurePlan,
            context={"facts": facts, "target_roles": target_roles, "direction": direction},
            temperature=0.1,
        )
    except LLMError:
        logger.warning("structure planner unavailable, using rules")
        plan = rule_based_plan(facts, target_roles, direction)
    return sanitize_plan(plan, facts)
