"""AI CV Builder (implemented in Phase 2)."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards as kb
from app.bot.utils import show
from app.database.models import User
from app.services.i18n import Translator

router = Router(name="cv_builder")


async def start_builder(
    target: Message | CallbackQuery, user: User, _: Translator, session: AsyncSession, state: FSMContext
) -> None:
    await show(target, _("common.coming_soon"), kb.back_kb(_, "resume_options"))
