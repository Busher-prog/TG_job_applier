"""Entry point.

    python -m app.main bot    # Telegram bot (polling, or webhook served by `api`)
    python -m app.main api    # FastAPI (health, legal pages, OAuth, webhook)
    python -m app.main all    # both in one process (webhook mode or local dev)
"""

from __future__ import annotations

import asyncio
import logging
import sys

from app.config import get_settings
from app.utils.logging import setup_logging

logger = logging.getLogger("app")


async def run_bot() -> None:
    from redis.asyncio import Redis

    from app.bot.factory import create_bot, create_dispatcher, create_storage, set_bot_commands
    from app.database.session import dispose_engine, init_engine

    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
    session_factory = init_engine()
    redis = Redis.from_url(settings.redis_url)
    bot = create_bot()
    dp = create_dispatcher(session_factory, storage=create_storage(), redis=redis)
    await set_bot_commands(bot)
    me = await bot.get_me()
    logger.info("Bot @%s started (mode=%s, ai=%s)", me.username, settings.bot_mode, settings.effective_ai_provider)
    try:
        if settings.bot_mode == "webhook":
            await bot.set_webhook(
                f"{settings.app_base_url.rstrip('/')}/webhooks/telegram",
                secret_token=settings.telegram_webhook_secret,
                drop_pending_updates=False,
            )
            from app.api import webhooks

            webhooks.configure(bot, dp)
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await redis.aclose()
        await dispose_engine()


async def run_api() -> None:
    import uvicorn

    from app.api.app import create_app

    config = uvicorn.Config(create_app(), host="0.0.0.0", port=8000, proxy_headers=True,
                            forwarded_allow_ips="*", log_level="info")
    await uvicorn.Server(config).serve()


async def run_all() -> None:
    await asyncio.gather(run_api(), run_bot())


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    mode = sys.argv[1] if len(sys.argv) > 1 else "bot"
    runners = {"bot": run_bot, "api": run_api, "all": run_all}
    if mode not in runners:
        raise SystemExit(f"Unknown mode {mode!r}. Use: bot | api | all")
    asyncio.run(runners[mode]())


if __name__ == "__main__":
    main()
