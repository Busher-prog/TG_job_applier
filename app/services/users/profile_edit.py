"""Manual edits of profile fields from the bot."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CandidateLanguage, CandidateSkill, Portfolio
from app.database.models.enums import SkillCategory
from app.database.repositories.audit import audit
from app.database.repositories.profiles import ProfileRepository
from app.schemas.common import clean_list, clean_str, normalize_email, normalize_phone, normalize_url
from app.schemas.cv import normalize_level
from app.services.cv.profile_service import normalize_skill


class ProfileEditError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_languages(text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for part in re.split(r"[\n;,]+", text):
        part = part.strip(" -–•")
        if not part:
            continue
        m = re.match(r"^(.+?)\s*(?:[-–—:(]\s*|\s+)(A1|A2|B1|B2|C1|C2|native|fluent|muttersprache|fließend|родной|рідна|свободно|вільно)\)?\s*$", part, re.I)
        if m:
            name, level = m.group(1).strip(), normalize_level(m.group(2))
        else:
            name, level = part, "Unknown"
        name = clean_str(name, 64)
        if name:
            result.append((name[:1].upper() + name[1:], level))
    return result[:15]


async def update_profile_field(session: AsyncSession, user_id: int, field: str, raw: str) -> None:
    profile = await ProfileRepository(session).get_or_create(user_id)
    text = raw.strip()
    if not text or len(text) > 2000:
        raise ProfileEditError("invalid_value")

    if field == "name":
        value = clean_str(text, 200)
        if not value or len(value) < 2:
            raise ProfileEditError("invalid_value")
        profile.full_name = value
    elif field == "email":
        value = normalize_email(text)
        if not value:
            raise ProfileEditError("invalid_email")
        profile.email = value
    elif field == "phone":
        value = normalize_phone(text)
        if not value:
            raise ProfileEditError("invalid_phone")
        profile.phone = value
    elif field == "location":
        parts = [p.strip() for p in text.split(",") if p.strip()]
        if not parts or len(text) > 200:
            raise ProfileEditError("invalid_value")
        profile.city = parts[0][:128]
        profile.country = parts[-1][:128] if len(parts) > 1 else profile.country
    elif field in ("linkedin", "portfolio"):
        url = normalize_url(text)
        if not url:
            raise ProfileEditError("invalid_url")
        if field == "linkedin":
            profile.linkedin_url = url
        else:
            profile.portfolio_url = url
            if url not in {p.url for p in profile.portfolios}:
                profile.portfolios.append(Portfolio(url=url, kind="portfolio"))
    elif field == "languages":
        items = parse_languages(text)
        if not items:
            raise ProfileEditError("invalid_value")
        profile.languages.clear()
        await session.flush()
        for name, level in items:
            profile.languages.append(CandidateLanguage(language=name, level=level))
    elif field in ("software", "skills"):
        names = clean_list(re.split(r"[,;\n]+", text), max_items=40, max_len=120)
        if not names:
            raise ProfileEditError("invalid_value")
        categories = (
            (SkillCategory.SOFTWARE.value, SkillCategory.TOOL.value)
            if field == "software"
            else (SkillCategory.HARD.value, SkillCategory.TECHNICAL.value)
        )
        target = categories[0]
        profile.skills[:] = [s for s in profile.skills if s.category not in categories]
        await session.flush()
        seen: set[str] = set()
        for name in names:
            key = normalize_skill(name)
            if key in seen:
                continue
            seen.add(key)
            profile.skills.append(
                CandidateSkill(name=name, name_normalized=key, category=target, source="user")
            )
    else:
        raise ProfileEditError("invalid_value")

    await session.flush()
    await audit(session, "profile.field_updated", user_id=user_id, field=field)
