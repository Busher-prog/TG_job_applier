"""ResumeDocument — the validated content + structure handed to the renderer.

AI agents produce parts of it; :func:`app.services.cv.generator.assemble_document`
merges them with the candidate facts so that employers, titles, dates and
institutions always come from the facts, never from the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import (
    LongStr,
    OptionalEmail,
    OptionalPhone,
    OptionalUrl,
    PartialDate,
    ShortStr,
    StrList,
)
from app.schemas.cv import LanguageLevelLiteral, normalize_level

TemplateCode = Literal["classic_ats", "modern", "creative"]
TEMPLATE_CODES: tuple[str, ...] = ("classic_ats", "modern", "creative")

SectionKey = Literal[
    "professional_summary",
    "experience",
    "achievements",
    "skills",
    "software",
    "transferable_skills",
    "education",
    "languages",
    "projects",
    "certifications",
    "portfolio",
    "additional_experience",
]
SECTION_KEYS: tuple[str, ...] = (
    "professional_summary", "experience", "achievements", "skills", "software", "transferable_skills",
    "education", "languages", "projects", "certifications", "portfolio", "additional_experience",
)


def dedupe_sections(v: object) -> object:
    if isinstance(v, list):
        seen: list[str] = []
        for item in v:
            if item in SECTION_KEYS and item not in seen:
                seen.append(item)
        return seen
    return v


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ResumeCandidate(_M):
    full_name: str = Field(min_length=2, max_length=200)
    headline: ShortStr = None
    email: OptionalEmail = None
    phone: OptionalPhone = None
    location: ShortStr = None
    linkedin_url: OptionalUrl = None
    portfolio_url: OptionalUrl = None
    other_links: list[OptionalUrl] = Field(default_factory=list)

    @field_validator("other_links", mode="after")
    @classmethod
    def _drop_empty(cls, v: list[str | None]) -> list[str | None]:
        return [x for x in v if x][:5]


class ResumeExperience(_M):
    id: str
    company: ShortStr = None
    job_title: ShortStr = None
    location: ShortStr = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    is_current: bool = False
    employment_type: str | None = None
    bullets: StrList = Field(default_factory=list)
    tools: StrList = Field(default_factory=list)


class ResumeEducation(_M):
    id: str
    institution: ShortStr = None
    degree: ShortStr = None
    specialization: ShortStr = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    status: str = "unknown"
    details: StrList = Field(default_factory=list)


class ResumeLanguage(_M):
    language: str
    level: LanguageLevelLiteral = "Unknown"

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v: object) -> str:
        return normalize_level(v)


class ResumeProject(_M):
    name: str
    description: LongStr = None
    role: ShortStr = None
    url: OptionalUrl = None
    technologies: StrList = Field(default_factory=list)


class ResumeCertification(_M):
    name: str
    issuer: ShortStr = None
    date: PartialDate = None
    url: OptionalUrl = None


class PortfolioLink(_M):
    title: ShortStr = None
    url: OptionalUrl = None


class ResumeDocument(_M):
    candidate: ResumeCandidate
    target_roles: StrList = Field(default_factory=list)
    professional_summary: LongStr = None
    experience: list[ResumeExperience] = Field(default_factory=list)
    additional_experience: list[ResumeExperience] = Field(default_factory=list)
    achievements: StrList = Field(default_factory=list)
    skills: StrList = Field(default_factory=list)
    soft_skills: StrList = Field(default_factory=list)
    software: StrList = Field(default_factory=list)
    transferable_skills: StrList = Field(default_factory=list)
    education: list[ResumeEducation] = Field(default_factory=list)
    languages: list[ResumeLanguage] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    certifications: list[ResumeCertification] = Field(default_factory=list)
    portfolio: list[PortfolioLink] = Field(default_factory=list)
    section_order: list[SectionKey] = Field(default_factory=list)
    template: TemplateCode = "classic_ats"
    document_language: str = Field(default="en", min_length=2, max_length=16)
    page_limit: int | None = Field(default=None, ge=1, le=4)
    density: int = Field(default=0, ge=0, le=3, description="Renderer compaction level")

    @field_validator("section_order", mode="before")
    @classmethod
    def _dedupe_sections(cls, v: object) -> object:
        return dedupe_sections(v)

    @field_validator("portfolio", mode="after")
    @classmethod
    def _valid_portfolio(cls, v: list[PortfolioLink]) -> list[PortfolioLink]:
        return [p for p in v if p.url][:6]

    @model_validator(mode="after")
    def _contact_required(self) -> "ResumeDocument":
        if not (self.candidate.email or self.candidate.phone):
            raise ValueError("A CV needs at least an email or a phone number")
        return self

    def has_content(self, section: str) -> bool:
        value = {
            "professional_summary": self.professional_summary,
            "experience": self.experience,
            "additional_experience": self.additional_experience,
            "achievements": self.achievements,
            "skills": self.skills or self.soft_skills,
            "software": self.software,
            "transferable_skills": self.transferable_skills,
            "education": self.education,
            "languages": self.languages,
            "projects": self.projects,
            "certifications": self.certifications,
            "portfolio": self.portfolio,
        }.get(section)
        return bool(value)

    def visible_sections(self) -> list[str]:
        order = [s for s in self.section_order if self.has_content(s)]
        # Never silently lose content: sections with data but missing from the order go last.
        for s in SECTION_KEYS:
            if s not in order and self.has_content(s) and s not in self.section_order:
                order.append(s)
        return order


# ----- Agent outputs ----------------------------------------------------------------------------


class StructurePlan(_M):
    """CV Structure Planner output."""

    profile_type: Literal["experienced", "student", "creative", "career_change", "entry_level"]
    section_order: list[SectionKey]
    relevant_experience_ids: list[str] = Field(default_factory=list)
    additional_experience_ids: list[str] = Field(default_factory=list)
    recommended_template: TemplateCode = "classic_ats"
    target_pages: int = Field(default=1, ge=1, le=3)
    rationale: str = ""

    @field_validator("section_order", mode="before")
    @classmethod
    def _dedupe(cls, v: object) -> object:
        return dedupe_sections(v)


class GeneratedExperience(_M):
    id: str
    bullets: StrList = Field(default_factory=list)


class GeneratedEducation(_M):
    id: str
    details: StrList = Field(default_factory=list)


class GeneratedProject(_M):
    name: str
    description: LongStr = None


class GeneratedContent(_M):
    """CV Content Generator output (text only — facts are merged in deterministically)."""

    headline: ShortStr = None
    professional_summary: LongStr = None
    experience: list[GeneratedExperience] = Field(default_factory=list)
    education: list[GeneratedEducation] = Field(default_factory=list)
    skills: StrList = Field(default_factory=list)
    soft_skills: StrList = Field(default_factory=list)
    software: StrList = Field(default_factory=list)
    transferable_skills: StrList = Field(default_factory=list)
    achievements: StrList = Field(default_factory=list)
    projects: list[GeneratedProject] = Field(default_factory=list)
