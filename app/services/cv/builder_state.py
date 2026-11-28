"""CV Builder interview state. Persisted on the profile (survives Redis loss / restarts)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database.models import CandidateProfile
from app.database.repositories.profiles import ProfileRepository
from app.schemas.cv import ParsedCV

STAGES: tuple[str, ...] = (
    "name", "email", "phone", "location", "linkedin", "portfolio",
    "direction", "target_role",
    "experience", "exp_followup", "exp_more",
    "adaptive",
    "education", "education_more",
    "skills", "languages", "extras",
    "cv_language", "design",
)
OPTIONAL: frozenset[str] = frozenset(
    {"email", "phone", "linkedin", "portfolio", "location", "adaptive", "education", "languages", "extras"}
)
SECTION_OF: dict[str, str] = {
    "name": "personal", "email": "personal", "phone": "personal", "location": "personal",
    "linkedin": "personal", "portfolio": "personal", "direction": "direction", "target_role": "direction",
    "experience": "experience", "exp_followup": "experience", "exp_more": "experience",
    "adaptive": "details", "education": "education", "education_more": "education", "skills": "skills",
    "languages": "languages", "extras": "extras", "cv_language": "final", "design": "final",
}


class BuilderDraft(BaseModel):
    stage: str = "name"
    done: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    facts: ParsedCV = Field(default_factory=ParsedCV)
    direction: str | None = None
    target_roles: list[str] = Field(default_factory=list)
    no_experience: bool = False
    exp_index: int | None = None
    followups: list[dict[str, str]] = Field(default_factory=list)
    adaptive: list[str] = Field(default_factory=list)
    adaptive_generated: bool = False
    adaptive_index: int = 0
    answers: list[dict[str, str]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    selected: list[str] = Field(default_factory=list)
    cv_language: str | None = None
    template: str | None = None
    preset_template: str | None = None

    def mark_done(self, stage: str) -> None:
        if stage not in self.done:
            self.done.append(stage)

    def applicable(self, stage: str) -> bool:
        if stage == "target_role":
            return self.direction == "known" and not self.target_roles
        if stage in ("experience",):
            return not self.no_experience
        if stage == "exp_followup":
            return bool(self.followups)
        if stage == "exp_more":
            return bool(self.facts.experience) and not self.no_experience
        if stage == "education_more":
            return bool(self.facts.education)
        if stage == "design":
            return self.preset_template is None
        return True

    def next_stage(self) -> str:
        for stage in STAGES:
            if stage in self.done or not self.applicable(stage):
                continue
            if stage == "adaptive" and self.adaptive_generated and self.adaptive_index >= len(self.adaptive):
                continue
            return stage
        return "generate"

    def prefill_from_facts(self, cv_language: str | None) -> None:
        """Skip questions whose answers we already have (no repeated questions)."""
        c = self.facts.candidate
        known = {
            "name": c.full_name, "email": c.email, "phone": c.phone, "location": c.city,
            "linkedin": c.linkedin_url, "portfolio": c.portfolio_url,
            "languages": self.facts.languages, "cv_language": cv_language,
        }
        for stage, value in known.items():
            if value:
                self.mark_done(stage)
        if self.facts.experience:
            self.mark_done("experience")
            self.mark_done("exp_followup")
        if self.facts.education:
            self.mark_done("education")
        if cv_language:
            self.cv_language = cv_language


def load_draft(profile: CandidateProfile) -> BuilderDraft | None:
    raw: dict[str, Any] | None = (profile.extra or {}).get("builder")
    return BuilderDraft.model_validate(raw) if raw else None


async def save_draft(session: AsyncSession, user_id: int, draft: BuilderDraft | None) -> None:
    profile = await ProfileRepository(session).get_or_create(user_id)
    extra = dict(profile.extra or {})
    if draft is None:
        extra.pop("builder", None)
    else:
        extra["builder"] = draft.model_dump(mode="json")
    profile.extra = extra
    flag_modified(profile, "extra")
    await session.flush()
