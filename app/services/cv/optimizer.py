"""CV Optimizer: transparent rule-based ATS checks + AI qualitative review."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.prompts import load_prompt, untrusted
from app.providers.llm import LLMError, get_llm
from app.schemas.common import StrList
from app.schemas.cv import ParsedCV
from app.services.cv.facts import facts_payload

logger = logging.getLogger(__name__)

NUMBER_IN_BULLET = re.compile(r"\d")


class OptimizerReview(BaseModel):
    strengths: StrList = Field(default_factory=list)
    issues: StrList = Field(default_factory=list)
    recommendations: StrList = Field(default_factory=list)
    missing_information: StrList = Field(default_factory=list)
    clarifying_questions: StrList = Field(default_factory=list)


@dataclass(slots=True)
class OptimizerReport:
    ats_score: int
    strengths: list[str] = field(default_factory=list)   # rule codes
    issues: list[str] = field(default_factory=list)      # rule codes
    review: OptimizerReview = field(default_factory=OptimizerReview)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ats_score": self.ats_score,
            "strengths": self.strengths,
            "issues": self.issues,
            "review": self.review.model_dump(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OptimizerReport":
        return cls(
            ats_score=data["ats_score"],
            strengths=data.get("strengths", []),
            issues=data.get("issues", []),
            review=OptimizerReview.model_validate(data.get("review", {})),
        )


PENALTIES = {
    "no_email": 15, "no_phone": 6, "no_summary": 8, "missing_dates": 12, "few_bullets": 8,
    "no_quantified": 5, "too_long": 8, "too_short": 10, "no_skills": 10, "no_languages": 4,
    "scanned": 20, "many_pages": 8, "long_paragraphs": 6, "no_experience_section": 8,
}


def ats_checks(parsed: ParsedCV, text: str, extraction_method: str = "text", page_count: int = 0) -> OptimizerReport:
    """Indicative ATS-readability score from explicit, explainable checks (0-100)."""
    issues: list[str] = []
    strengths: list[str] = []
    c = parsed.candidate
    words = len(text.split())
    exp = parsed.experience
    months = parsed.total_experience_months or 0

    if not c.email:
        issues.append("no_email")
    if not c.phone:
        issues.append("no_phone")
    if c.email and c.phone:
        strengths.append("contacts_complete")
    if parsed.summary:
        strengths.append("has_summary")
    else:
        issues.append("no_summary")
    if exp:
        if any(not e.start_date for e in exp):
            issues.append("missing_dates")
        else:
            strengths.append("clear_dates")
        bullets = [b for e in exp for b in (*e.responsibilities, *e.achievements)]
        if len(bullets) < max(2, len(exp)):
            issues.append("few_bullets")
        if any(NUMBER_IN_BULLET.search(b) for b in bullets):
            strengths.append("quantified_results")
        elif bullets:
            issues.append("no_quantified")
    elif not parsed.education:
        issues.append("no_experience_section")
    if parsed.skills.all():
        strengths.append("skills_listed")
    else:
        issues.append("no_skills")
    if parsed.languages:
        strengths.append("languages_listed")
    else:
        issues.append("no_languages")
    limit = 900 if months < 96 else 1400
    if words > limit:
        issues.append("too_long")
    if words < 120:
        issues.append("too_short")
    if extraction_method == "ocr":
        issues.append("scanned")
    if page_count > 3:
        issues.append("many_pages")
    if any(len(p.split()) > 90 for p in text.split("\n\n")):
        issues.append("long_paragraphs")

    score = 100 - sum(PENALTIES.get(i, 0) for i in issues)
    return OptimizerReport(ats_score=max(5, min(100, score)), strengths=strengths, issues=issues)


async def analyze_cv(
    parsed: ParsedCV, text: str, *, ui_language: str, target_roles: list[str],
    extraction_method: str = "text", page_count: int = 0,
) -> OptimizerReport:
    report = ats_checks(parsed, text, extraction_method, page_count)
    try:
        report.review = await get_llm().generate_json(
            task="cv_optimizer",
            system=load_prompt("cv_optimizer"),
            user="Review this CV.\n" + untrusted("cv_document", text[:20000])
            + "\n" + untrusted("extracted_facts", facts_payload(parsed))
            + "\n" + untrusted("request", {"interface_language": ui_language, "target_roles": target_roles,
                                           "rule_based_findings": report.issues}),
            schema=OptimizerReview,
            context={"report": report, "parsed": parsed, "language": ui_language},
            temperature=0.3,
        )
    except LLMError:
        logger.warning("optimizer AI review unavailable; rule-based findings only")
    return report
