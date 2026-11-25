"""CV examples (implemented in Phase 2)."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.bot.utils import show
from app.services.i18n import Translator

router = Router(name="cv_examples")


async def show_examples(target: Message | CallbackQuery, _: Translator, state: FSMContext) -> None:
    await show(target, _("common.coming_soon"), kb.back_kb(_, "resume_options"))
