"""Resumes, their versions and rendering templates."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, TimestampMixin
from app.database.models.enums import ResumeStatus


class Resume(IdMixin, TimestampMixin, Base):
    __tablename__ = "resumes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=ResumeStatus.PROCESSING.value, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    original_file_key: Mapped[str | None] = mapped_column(String(500))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(String(16))
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    document_language: Mapped[str | None] = mapped_column(String(16))
    template_code: Mapped[str | None] = mapped_column(String(32))
    parent_resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    job_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_listings.id", ondelete="SET NULL")
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL", use_alter=True)
    )
    error_code: Mapped[str | None] = mapped_column(String(64))

    versions: Mapped[list["ResumeVersion"]] = relationship(
        back_populates="resume",
        cascade="all, delete-orphan",
        foreign_keys="ResumeVersion.resume_id",
        order_by="ResumeVersion.version_number",
    )


class ResumeVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("resume_id", "version_number"),)

    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    template_code: Mapped[str] = mapped_column(String(32), nullable=False)
    document_language: Mapped[str] = mapped_column(String(16), nullable=False)
    pdf_file_key: Mapped[str | None] = mapped_column(String(500))
    docx_file_key: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer)
    change_note: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    resume: Mapped[Resume] = relationship(back_populates="versions", foreign_keys=[resume_id])


class ResumeTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "resume_templates"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    layout: Mapped[str] = mapped_column(String(32), default="single_column", nullable=False)
    recommended_roles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    ats_friendly: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
