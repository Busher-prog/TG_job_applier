"""Telegram webhook endpoint (BOT_MODE=webhook)."""

from __future__ import annotations

import hmac
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings

router = APIRouter()
_bot: Bot | None = None
_dp: Dispatcher | None = None


def configure(bot: Bot, dp: Dispatcher) -> None:
    global _bot, _dp
    _bot, _dp = bot, dp


@router.post("/webhooks/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    secret = get_settings().telegram_webhook_secret
    if not secret or not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        secret, x_telegram_bot_api_secret_token
    ):
        raise HTTPException(status_code=403)
    if _bot is None or _dp is None:
        raise HTTPException(status_code=503)
    update = Update.model_validate(await request.json(), context={"bot": _bot})
    await _dp.feed_update(_bot, update)
    return {"ok": True}
