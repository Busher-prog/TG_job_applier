"""Candidate profile and its structured sections."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from app.database.models.user import User


class CandidateProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidate_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    full_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(128))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    headline: Mapped[str | None] = mapped_column(String(300))
    summary: Mapped[str | None] = mapped_column(Text)
    primary_field: Mapped[str | None] = mapped_column(String(200))
    target_roles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    career_direction: Mapped[str | None] = mapped_column(String(32))
    career_goal: Mapped[str | None] = mapped_column(Text)
    total_experience_months: Mapped[int | None] = mapped_column(Integer)
    has_no_experience: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Work authorization is explicit user input — never inferred from nationality.
    work_authorization: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    needs_visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    certifications: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    projects: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source: Mapped[str | None] = mapped_column(String(32))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="profile")
    experiences: Mapped[list["WorkExperience"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="WorkExperience.position"
    )
    education: Mapped[list["EducationRecord"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="EducationRecord.position"
    )
    skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    languages: Mapped[list["CandidateLanguage"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    portfolios: Mapped[list["Portfolio"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class WorkExperience(IdMixin, TimestampMixin, Base):
    __tablename__ = "work_experiences"

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    # Dates kept as partial ISO strings ("2023", "2023-04") — CVs rarely have full dates.
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(32))
    responsibilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    achievements: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    tools: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped[CandidateProfile] = relationship(back_populates="experiences")


class EducationRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "education_records"

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    institution: Mapped[str | None] = mapped_column(String(300))
    degree: Mapped[str | None] = mapped_column(String(200))
    specialization: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str | None] = mapped_column(String(32))
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped[CandidateProfile] = relationship(back_populates="education")


class CandidateSkill(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (UniqueConstraint("profile_id", "category", "name_normalized"),)

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="cv", nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    profile: Mapped[CandidateProfile] = relationship(back_populates="skills")


class CandidateLanguage(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidate_languages"
    __table_args__ = (UniqueConstraint("profile_id", "language"),)

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="Unknown", nullable=False)

    profile: Mapped[CandidateProfile] = relationship(back_populates="languages")


class Portfolio(IdMixin, TimestampMixin, Base):
    __tablename__ = "portfolios"

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="portfolio", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    profile: Mapped[CandidateProfile] = relationship(back_populates="portfolios")
