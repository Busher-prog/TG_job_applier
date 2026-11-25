"""A slash command always interrupts pending text input.

Only the FSM *state* is cleared — FSM data and onboarding progress (stored on
the user record) are kept, so "Continue setup" resumes where the user left.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject


class CommandResetMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and (event.text or "").startswith("/"):
            state: FSMContext | None = data.get("state")
            if state is not None and await state.get_state() is not None:
                await state.set_state(None)
                data["raw_state"] = None
        return await handler(event, data)
