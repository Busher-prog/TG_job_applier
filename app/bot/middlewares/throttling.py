"""Per-user rate limiting backed by Redis (falls back to memory)."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, redis: Any | None = None, limit: int = 20, window_seconds: int = 10) -> None:
        self.redis = redis
        self.limit = limit
        self.window = window_seconds
        self._memory: dict[int, list[float]] = {}

    async def _hit(self, user_id: int) -> int:
        if self.redis is not None:
            try:
                key = f"rl:{user_id}:{int(time.time() // self.window)}"
                count = await self.redis.incr(key)
                if count == 1:
                    await self.redis.expire(key, self.window)
                return int(count)
            except Exception:  # Redis unavailable — degrade gracefully
                logger.warning("rate limiter: redis unavailable, using memory")
        now = time.monotonic()
        hits = [t for t in self._memory.get(user_id, []) if now - t < self.window]
        hits.append(now)
        self._memory[user_id] = hits
        return len(hits)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)
        count = await self._hit(tg_user.id)
        if count > self.limit:
            if count == self.limit + 1 and isinstance(event, CallbackQuery):
                await event.answer("⏳", show_alert=False)
            elif count == self.limit + 1 and isinstance(event, Message):
                from app.services.i18n import Translator
                from app.services.users.service import detect_language

                await event.answer(Translator(detect_language(tg_user.language_code))("common.rate_limited"))
            return None
        return await handler(event, data)
