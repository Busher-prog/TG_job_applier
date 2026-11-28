"""Cover letters, applications, email connections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdMixin, TimestampMixin
from app.database.models.enums import ApplicationStatus


class CoverLetter(IdMixin, TimestampMixin, Base):
    __tablename__ = "cover_letters"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_listings.id", ondelete="SET NULL"), index=True
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    greeting: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    tone: Mapped[str] = mapped_column(String(32), default="professional", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (Index("ix_applications_user_status", "user_id", "status"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_listings.id", ondelete="SET NULL"), index=True
    )
    resume_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL")
    )
    cover_letter_id: Mapped[int | None] = mapped_column(
        ForeignKey("cover_letters.id", ondelete="SET NULL")
    )
    recruiter_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("recruiter_contacts.id", ondelete="SET NULL")
    )
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    job_title: Mapped[str] = mapped_column(String(300), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=ApplicationStatus.DRAFT.value, nullable=False
    )
    from_email: Mapped[str | None] = mapped_column(String(320))
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    provider_thread_id: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_charged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)


class EmailConnection(IdMixin, TimestampMixin, Base):
    __tablename__ = "email_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), default="gmail", nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    # Fernet-encrypted refresh token. Never log or expose.
    encrypted_refresh_token: Mapped[bytes | None] = mapped_column(LargeBinary)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(200))
