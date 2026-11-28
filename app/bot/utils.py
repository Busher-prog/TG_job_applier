"""Shared helpers for handlers."""

from __future__ import annotations

import html
import io
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.database.models import CandidateProfile
from app.providers.llm import LLMError, get_llm
from app.services.cv.profile_service import summarize_profile
from app.services.i18n import Translator

logger = logging.getLogger(__name__)

ONBOARDING_STEPS: tuple[str, ...] = (
    "step_cv", "step_profile", "step_targets", "step_preferences", "step_salary", "step_confirm",
)
MAX_VOICE_SECONDS = 180


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def progress(_: Translator, step_key: str) -> str:
    idx = ONBOARDING_STEPS.index(step_key) + 1
    return "<i>" + _(
        "onboarding.progress",
        current=idx,
        total=len(ONBOARDING_STEPS),
        name=_(f"onboarding.{step_key}"),
    ) + "</i>\n\n"


async def show(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *,
    edit: bool = True,
) -> Message | None:
    """Edit the callback's message in place when possible, else send a new one."""
    if isinstance(target, CallbackQuery):
        message = target.message
        if edit and isinstance(message, Message) and message.text is not None:
            try:
                result = await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
                return result if isinstance(result, Message) else message
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc):
                    return message
        if isinstance(message, Message):
            return await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
        return None
    return await target.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)


async def get_text_input(message: Message, bot: Bot, _: Translator, lang_hint: str | None = None) -> str | None:
    """Return text from a text or voice message. Sends feedback on failure."""
    if message.text:
        return message.text.strip()
    voice = message.voice or message.audio
    if voice is None:
        return None
    if (voice.duration or 0) > MAX_VOICE_SECONDS:
        await message.answer(_("voice.too_long"))
        return None
    status = await message.answer(_("voice.transcribing"))
    try:
        buffer = io.BytesIO()
        await bot.download(voice, destination=buffer)
        text = await get_llm().transcribe(buffer.getvalue(), "voice.ogg", lang_hint)
    except (LLMError, Exception) as exc:  # network errors from Telegram as well
        logger.warning("voice transcription failed: %s", type(exc).__name__)
        text = ""
    try:
        await status.delete()
    except TelegramBadRequest:
        pass
    if not text:
        await message.answer(_("voice.failed"))
        return None
    return text


def format_experience(_: Translator, months: int | None, no_experience: bool) -> str:
    if no_experience or months is None:
        return _("profile.no_experience") if no_experience else _("common.not_set")
    if months < 12:
        return _("profile.less_than_year")
    years = months // 12
    return _("profile.more_than_years", years=_.plural("units.years", years))


def format_profile(_: Translator, profile: CandidateProfile, detailed: bool = False) -> str:
    s = summarize_profile(profile)
    lines: list[str] = []

    def add(label_key: str, value: str | None) -> None:
        if value:
            lines.append(f"<b>{_(label_key)}:</b> {esc(value)}")

    add("profile.field_name", s.full_name or _("common.not_set"))
    add("profile.field_main", s.primary_field)
    lines.append(f"<b>{_('profile.field_experience')}:</b> {esc(format_experience(_, s.experience_months, s.has_no_experience))}")
    for language, level in s.languages:
        lines.append(f"<b>{esc(language)}:</b> {esc(level)}")
    add("profile.field_software", ", ".join(s.software) if s.software else None)
    if detailed:
        add("profile.field_skills", ", ".join(s.skills) if s.skills else None)
        add("profile.field_last_job", s.last_job)
        add("profile.field_email", s.email)
        add("profile.field_phone", s.phone)
        add("profile.field_location", s.location)
        add("profile.field_linkedin", profile.linkedin_url)
        add("profile.field_portfolio", profile.portfolio_url)
    return "\n".join(lines)
