"""Blocks personal-data features until the user has given consent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.services.users.service import has_valid_consent


class ConsentRequiredMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        if user is None:
            return None
        if await has_valid_consent(data["session"], user):
            return await handler(event, data)
        from app.bot.handlers.start import send_consent_screen

        _ = data["_"]
        if isinstance(event, CallbackQuery):
            await event.answer(_("consent.required"), show_alert=True)
            if isinstance(event.message, Message):
                await send_consent_screen(event.message, _, user.interface_language)
        elif isinstance(event, Message):
            await event.answer(_("consent.required"))
            await send_consent_screen(event, _, user.interface_language)
        return None
