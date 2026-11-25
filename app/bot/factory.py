"""Bot and Dispatcher construction."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.handlers import (
    cv_builder,
    cv_examples,
    cv_optimizer,
    cv_preview,
    fallback,
    menu,
    onboarding,
    profile,
    resumes,
    search_onboarding,
    settings,
    start,
)
from app.bot.middlewares import DbSessionMiddleware, ThrottlingMiddleware, UserMiddleware
from app.bot.middlewares.command_reset import CommandResetMiddleware
from app.config import SUPPORTED_LANGUAGES, get_settings
from app.services.i18n import Translator, gettext

logger = logging.getLogger(__name__)

BOT_COMMANDS = (
    "start", "jobs", "newjobs", "cv", "createcv", "optimizecv", "saved",
    "applications", "profile", "settings", "subscription", "help",
)


def create_bot(token: str | None = None) -> Bot:
    return Bot(
        token=token or get_settings().telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_storage() -> BaseStorage:
    settings = get_settings()
    if settings.app_env == "test":
        return MemoryStorage()
    from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage

    return RedisStorage.from_url(
        settings.redis_url,
        key_builder=DefaultKeyBuilder(with_destiny=True),
        state_ttl=60 * 60 * 24 * 30,
        data_ttl=60 * 60 * 24 * 30,
    )


def create_dispatcher(
    session_factory: async_sessionmaker[AsyncSession],
    storage: BaseStorage | None = None,
    redis: object | None = None,
) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage())

    cfg = get_settings()
    throttling = ThrottlingMiddleware(
        redis=redis, limit=cfg.rate_limit_events, window_seconds=cfg.rate_limit_window_seconds
    )
    dp.message.outer_middleware(throttling)
    dp.callback_query.outer_middleware(throttling)
    for observer in (dp.message, dp.callback_query, dp.pre_checkout_query):
        observer.outer_middleware(DbSessionMiddleware(session_factory))
        observer.outer_middleware(UserMiddleware())
    dp.message.outer_middleware(CommandResetMiddleware())

    # Order matters: command/navigation routers first, state-bound input routers later.
    dp.include_routers(
        start.router,
        menu.router,
        settings.router,
        profile.router,
        resumes.router,
        cv_examples.router,
        cv_builder.router,
        cv_optimizer.router,
        cv_preview.router,
        search_onboarding.router,
        onboarding.router,
        fallback.router,
    )

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        # Log type only — exception messages may contain user data.
        logger.error("Unhandled error in update %s: %s", event.update.update_id,
                     type(event.exception).__name__, exc_info=event.exception)
        update = event.update
        target = update.message or (update.callback_query.message if update.callback_query else None)
        user = update.message.from_user if update.message else (
            update.callback_query.from_user if update.callback_query else None)
        if target is not None and user is not None:
            from app.services.users.service import detect_language

            try:
                await target.answer(Translator(detect_language(user.language_code))("common.error_generic"))
            except Exception:  # pragma: no cover - best effort
                pass
        return True

    return dp


async def set_bot_commands(bot: Bot) -> None:
    for lang in SUPPORTED_LANGUAGES:
        commands = [BotCommand(command=c, description=gettext(lang, f"commands.{c}")) for c in BOT_COMMANDS]
        await bot.set_my_commands(commands, language_code=None if lang == "en" else lang)
