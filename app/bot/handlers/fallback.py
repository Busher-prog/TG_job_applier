"""Catch-all for unexpected input — registered last."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards as kb
from app.services.i18n import Translator

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message, _: Translator) -> None:
    await message.answer(_("common.unknown_input"), reply_markup=kb.to_menu_kb(_))


@router.callback_query()
async def unknown_callback(call: CallbackQuery, _: Translator) -> None:
    await call.answer(_("common.not_found"))
