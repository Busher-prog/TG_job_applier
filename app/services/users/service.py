"""User lifecycle: registration, language, consent, export, deletion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, get_settings
from app.database.models import (
    Application,
    AuditLog,
    ConsentRecord,
    CoverLetter,
    EmailConnection,
    Resume,
    SearchPreference,
    User,
)
from app.database.models.enums import ConsentType, OnboardingStep
from app.database.repositories.audit import audit
from app.database.repositories.profiles import ProfileRepository
from app.database.repositories.users import UserRepository
from app.providers.storage import get_storage, user_prefix


def detect_language(telegram_code: str | None) -> str:
    if not telegram_code:
        return DEFAULT_LANGUAGE
    code = telegram_code.split("-")[0].lower()
    if code in SUPPORTED_LANGUAGES:
        return code
    if code == "be":
        return "ru"
    return DEFAULT_LANGUAGE


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
) -> tuple[User, bool]:
    repo = UserRepository(session)
    user = await repo.get_by_telegram_id(telegram_id)
    created = False
    if user is None:
        settings = get_settings()
        user = await repo.create(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            telegram_language_code=language_code,
            interface_language=detect_language(language_code),
            is_admin=telegram_id in settings.admin_telegram_ids,
        )
        await audit(session, "user.registered", user_id=user.id)
        created = True
    else:
        user.username = username
        user.first_name = first_name
    await repo.touch(user)
    return user, created


async def has_valid_consent(session: AsyncSession, user: User) -> bool:
    repo = UserRepository(session)
    record = await repo.latest_consent(user.id, ConsentType.DATA_PROCESSING.value)
    return bool(
        record
        and record.granted
        and record.revoked_at is None
        and record.document_version == get_settings().privacy_policy_version
    )


async def grant_consent(session: AsyncSession, user: User) -> None:
    repo = UserRepository(session)
    version = get_settings().privacy_policy_version
    for ctype in (ConsentType.PRIVACY_POLICY, ConsentType.DATA_PROCESSING):
        await repo.add_consent(user.id, ctype.value, version, True, user.interface_language)
    if user.onboarding_step in (OnboardingStep.WELCOME.value, OnboardingStep.CONSENT.value):
        user.onboarding_step = OnboardingStep.RESUME.value
    await audit(session, "consent.granted", user_id=user.id, version=version)


async def decline_consent(session: AsyncSession, user: User) -> None:
    repo = UserRepository(session)
    await repo.add_consent(
        user.id, ConsentType.DATA_PROCESSING.value, get_settings().privacy_policy_version, False,
        user.interface_language,
    )
    user.onboarding_step = OnboardingStep.CONSENT.value
    await audit(session, "consent.declined", user_id=user.id)


async def set_interface_language(session: AsyncSession, user: User, lang: str) -> None:
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError("unsupported language")
    user.interface_language = lang
    await audit(session, "settings.interface_language", user_id=user.id, value=lang)


async def export_user_data(session: AsyncSession, user: User) -> bytes:
    """GDPR Art. 15/20 export as JSON (without secrets)."""
    await session.flush()
    await session.refresh(user)
    profile = await ProfileRepository(session).get_full(user.id)
    consents = await session.scalars(select(ConsentRecord).where(ConsentRecord.user_id == user.id))

    def row(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
        exclude = exclude or set()
        return {
            c.key: getattr(obj, c.key)
            for c in obj.__table__.columns
            if c.key not in exclude
        }

    data: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "user": row(user),
        "consents": [row(c) for c in consents],
    }
    if profile:
        data["profile"] = row(profile)
        data["work_experiences"] = [row(e) for e in profile.experiences]
        data["education"] = [row(e) for e in profile.education]
        data["skills"] = [row(s) for s in profile.skills]
        data["languages"] = [row(lang) for lang in profile.languages]
        data["portfolios"] = [row(p) for p in profile.portfolios]
    data["resumes"] = [
        row(r, {"extracted_text"}) for r in await session.scalars(select(Resume).where(Resume.user_id == user.id))
    ]
    pref = await session.scalar(select(SearchPreference).where(SearchPreference.user_id == user.id))
    data["search_preferences"] = row(pref) if pref else None
    data["cover_letters"] = [
        row(c) for c in await session.scalars(select(CoverLetter).where(CoverLetter.user_id == user.id))
    ]
    data["applications"] = [
        row(a) for a in await session.scalars(select(Application).where(Application.user_id == user.id))
    ]
    data["email_connections"] = [
        row(e, {"encrypted_refresh_token"})
        for e in await session.scalars(select(EmailConnection).where(EmailConnection.user_id == user.id))
    ]
    await audit(session, "user.data_exported", user_id=user.id)
    return json.dumps(data, ensure_ascii=False, indent=2, default=str).encode("utf-8")


async def delete_account(session: AsyncSession, user: User) -> None:
    """Hard-delete the user, cascading to all personal data, and wipe stored files."""
    user_id = user.id
    await get_storage().delete_prefix(user_prefix(user_id))
    # Keep anonymised audit trail (user_id is SET NULL by FK).
    session.add(AuditLog(user_id=None, actor="user", action="user.deleted", meta={}))
    await session.execute(delete(User).where(User.id == user_id))
