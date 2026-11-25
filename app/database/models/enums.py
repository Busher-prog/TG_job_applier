"""String enums shared by models and services.

Stored as plain VARCHAR columns (not native PG enums) so that adding a value
does not require an ALTER TYPE migration.
"""

from __future__ import annotations

from enum import StrEnum


class OnboardingStep(StrEnum):
    WELCOME = "welcome"
    CONSENT = "consent"
    RESUME = "resume"
    PROFILE_CONFIRM = "profile_confirm"
    TARGET_JOBS = "target_jobs"
    LOCATION = "location"
    WORK_FORMAT = "work_format"
    EMPLOYMENT_TYPE = "employment_type"
    SALARY = "salary"
    EXCLUSIONS = "exclusions"
    ADDITIONAL = "additional"
    SEARCH_CONFIRM = "search_confirm"
    COMPLETED = "completed"


class ConsentType(StrEnum):
    PRIVACY_POLICY = "privacy_policy"
    DATA_PROCESSING = "data_processing"
    EMAIL_SEND = "email_send"
    EMAIL_READ = "email_read"


class ResumeKind(StrEnum):
    UPLOADED = "uploaded"
    GENERATED = "generated"
    OPTIMIZED = "optimized"
    TAILORED = "tailored"


class ResumeStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class SkillCategory(StrEnum):
    HARD = "hard"
    SOFT = "soft"
    SOFTWARE = "software"
    TOOL = "tool"
    TECHNICAL = "technical"


class LanguageLevel(StrEnum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"
    NATIVE = "Native"
    FLUENT = "Fluent"
    UNKNOWN = "Unknown"


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    MANUALLY_APPLIED = "manually_applied"
    REPLIED = "replied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"


class ApplicationMethod(StrEnum):
    EMAIL = "email"
    ATS = "ats"
    MANUAL = "manual"


class MatchCategory(StrEnum):
    HIGH = "high"
    GOOD = "good"
    CONDITIONAL = "conditional"
    HIDDEN = "hidden"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
