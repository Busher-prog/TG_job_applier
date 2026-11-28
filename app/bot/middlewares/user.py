"""Loads or registers the Telegram user and injects translator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser

from app.services.i18n import Translator
from app.services.users.service import get_or_create_user


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        session = data["session"]
        user, created = await get_or_create_user(
            session, tg_user.id, tg_user.username, tg_user.first_name, tg_user.language_code
        )
        if user.is_blocked:
            return None
        data["user"] = user
        data["user_created"] = created
        data["_"] = Translator(user.interface_language)
        return await handler(event, data)
