"""Job-search onboarding steps 13-20 (implemented in Phase 3)."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.utils import show
from app.database.models import User
from app.services.i18n import Translator

router = Router(name="search_onboarding")


async def resume_step(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    await show(
        target,
        _("profile.confirmed") + "\n\n" + _("profile.next_steps_pending") + "\n\n" + _("common.coming_soon"),
        kb.to_menu_kb(_),
    )
