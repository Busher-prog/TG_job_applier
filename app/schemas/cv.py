"""Structured CV data extracted from documents or collected by the CV Builder."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import (
    LongStr,
    OptionalEmail,
    OptionalPhone,
    OptionalUrl,
    PartialDate,
    ShortStr,
    StrList,
    clean_str,
    is_present,
)

LanguageLevelLiteral = Literal["A1", "A2", "B1", "B2", "C1", "C2", "Native", "Fluent", "Unknown"]
LANGUAGE_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2", "Native", "Fluent", "Unknown")

_LEVEL_ALIASES = {
    "native speaker": "Native", "mother tongue": "Native", "muttersprache": "Native",
    "родной": "Native", "рідна": "Native", "native": "Native",
    "fluent": "Fluent", "fließend": "Fluent", "свободно": "Fluent", "вільно": "Fluent",
    "свободный": "Fluent", "вільний": "Fluent",
}


def normalize_level(value: Any) -> str:
    if value is None:
        return "Unknown"
    text = str(value).strip()
    upper = text.upper()
    for lvl in ("A1", "A2", "B1", "B2", "C1", "C2"):
        if upper.startswith(lvl):
            return lvl
    lower = text.lower()
    for alias, lvl in _LEVEL_ALIASES.items():
        if alias in lower:
            return lvl
    return "Unknown"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class CandidateContact(_Model):
    full_name: ShortStr = None
    email: OptionalEmail = None
    phone: OptionalPhone = None
    city: ShortStr = None
    country: ShortStr = None
    linkedin_url: OptionalUrl = None
    portfolio_url: OptionalUrl = None
    other_links: list[OptionalUrl] = Field(default_factory=list)

    @field_validator("other_links", mode="after")
    @classmethod
    def _drop_empty(cls, v: list[str | None]) -> list[str | None]:
        return [x for x in v if x][:10]


class ExperienceItem(_Model):
    company: ShortStr = None
    job_title: ShortStr = None
    location: ShortStr = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    is_current: bool = False
    employment_type: (
        Literal["full_time", "part_time", "internship", "freelance", "contract", "volunteer", "other"] | None
    ) = None
    responsibilities: StrList = Field(default_factory=list)
    achievements: StrList = Field(default_factory=list)
    tools: StrList = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _present_end(cls, data: Any) -> Any:
        if isinstance(data, dict) and is_present(data.get("end_date")):
            data = {**data, "is_current": True, "end_date": None}
        if isinstance(data, dict) and data.get("employment_type") not in (
            None, "full_time", "part_time", "internship", "freelance", "contract", "volunteer", "other",
        ):
            data = {**data, "employment_type": "other"}
        return data

    @model_validator(mode="after")
    def _chronology(self) -> "ExperienceItem":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            # Do not silently swap user dates; flag by dropping the impossible end date.
            self.end_date = None
        return self

    @property
    def is_empty(self) -> bool:
        return not (self.company or self.job_title)


class EducationItem(_Model):
    institution: ShortStr = None
    degree: ShortStr = None
    specialization: ShortStr = None
    start_date: PartialDate = None
    end_date: PartialDate = None
    status: Literal["completed", "in_progress", "incomplete", "unknown"] = "unknown"

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, v: Any) -> str:
        return v if v in ("completed", "in_progress", "incomplete", "unknown") else "unknown"


class SkillsBlock(_Model):
    hard: StrList = Field(default_factory=list)
    soft: StrList = Field(default_factory=list)
    software: StrList = Field(default_factory=list)
    tools: StrList = Field(default_factory=list)
    technical: StrList = Field(default_factory=list)

    def all(self) -> list[str]:
        return [*self.hard, *self.software, *self.tools, *self.technical, *self.soft]


class LanguageItem(_Model):
    language: str
    level: LanguageLevelLiteral = "Unknown"

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, v: Any) -> str:
        return normalize_level(v)

    @field_validator("language", mode="before")
    @classmethod
    def _lang(cls, v: Any) -> str:
        text = clean_str(v, 64)
        if not text:
            raise ValueError("language is required")
        return text[:1].upper() + text[1:]


class CertificationItem(_Model):
    name: str
    issuer: ShortStr = None
    date: PartialDate = None
    url: OptionalUrl = None


class ProjectItem(_Model):
    name: str
    description: LongStr = None
    role: ShortStr = None
    url: OptionalUrl = None
    technologies: StrList = Field(default_factory=list)


class ParsedCV(_Model):
    """Output of the CV Parser agent."""

    candidate: CandidateContact = Field(default_factory=CandidateContact)
    headline: ShortStr = None
    summary: LongStr = None
    primary_field: ShortStr = Field(default=None, description="Main professional area, e.g. 'Content Creation'")
    total_experience_months: int | None = Field(default=None, ge=0, le=720)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    skills: SkillsBlock = Field(default_factory=SkillsBlock)
    languages: list[LanguageItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    detected_language: ShortStr = Field(default=None, description="ISO 639-1 code of the CV text")
    warnings: StrList = Field(default_factory=list)

    @field_validator("experience", mode="after")
    @classmethod
    def _drop_empty_exp(cls, v: list[ExperienceItem]) -> list[ExperienceItem]:
        return [e for e in v if not e.is_empty][:30]

    @field_validator("languages", mode="after")
    @classmethod
    def _dedupe_languages(cls, v: list[LanguageItem]) -> list[LanguageItem]:
        seen: dict[str, LanguageItem] = {}
        for item in v:
            key = item.language.lower()
            if key not in seen or seen[key].level == "Unknown":
                seen[key] = item
        return list(seen.values())
