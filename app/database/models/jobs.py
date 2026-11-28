"""Search preferences, job sources, listings, matches, contacts, saved jobs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdMixin, TimestampMixin


class SearchPreference(IdMixin, TimestampMixin, Base):
    __tablename__ = "search_preferences"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    target_roles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    suggested_roles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    search_all_matching: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    location_mode: Mapped[str | None] = mapped_column(String(32))
    cities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    countries: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    work_formats: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    employment_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(8))
    salary_is_gross: Mapped[bool | None] = mapped_column(Boolean)
    salary_any: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exclusions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    preferred_industries: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    has_work_permit: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    needs_visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_sources"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    jobs_fetched_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class JobListing(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_listings"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_job_listings_status_published", "status", "published_at"),
    )

    source_id: Mapped[int | None] = mapped_column(ForeignKey("job_sources.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    country: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(32))
    work_format: Mapped[str | None] = mapped_column(String(16))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(8))
    salary_payment_count: Mapped[int | None] = mapped_column(Integer)
    salary_is_gross: Mapped[bool | None] = mapped_column(Boolean)
    required_skills: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    preferred_skills: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    required_experience: Mapped[str | None] = mapped_column(String(200))
    language_requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    required_licenses: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    visa_sponsorship: Mapped[bool | None] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    application_url: Mapped[str | None] = mapped_column(String(1000))
    application_email: Mapped[str | None] = mapped_column(String(320))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(String(64))


class JobMatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_listing_id"),
        Index("ix_job_matches_user_score", "user_id", "score"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_listing_id: Mapped[int] = mapped_column(
        ForeignKey("job_listings.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    hard_filter_status: Mapped[str] = mapped_column(String(16), default="pass", nullable=False)
    component_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    missing_requirements: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    unverified_requirements: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    listing_content_hash: Mapped[str | None] = mapped_column(String(64))
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RecruiterContact(IdMixin, TimestampMixin, Base):
    __tablename__ = "recruiter_contacts"
    __table_args__ = (UniqueConstraint("job_listing_id", "email"),)

    job_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_listings.id", ondelete="CASCADE"), index=True
    )
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    application_url: Mapped[str | None] = mapped_column(String(1000))
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    contact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    accepts_applications: Mapped[bool | None] = mapped_column(Boolean)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=9, nullable=False)


class SavedJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_listing_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_listing_id: Mapped[int] = mapped_column(
        ForeignKey("job_listings.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
