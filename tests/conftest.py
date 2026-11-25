"""Test configuration. Uses a real PostgreSQL database (TEST_DATABASE_URL)."""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="copilot-test-")
os.environ.update(
    {
        "APP_ENV": "test",
        "MOCK_MODE": "true",
        "AI_PROVIDER": "mock",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot_test"
        ),
        "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_PATH": os.path.join(_TMP, "storage"),
        "ENCRYPTION_KEY": "test-encryption-passphrase",
        "TELEGRAM_BOT_TOKEN": "123456:TEST-TOKEN-FOR-UNIT-TESTS-ONLY-0000000",
        "APP_BASE_URL": "https://copilot.example.com",
        "RATE_LIMIT_EVENTS": "10000",
    }
)

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

from app.database.models import Base  # noqa: E402
from app.providers.llm import set_llm  # noqa: E402
from app.providers.storage import LocalStorage, set_storage  # noqa: E402
from tests.fixtures import make_sample_docx, make_sample_pdf  # noqa: E402


@pytest.fixture(scope="session")
def sample_pdf() -> bytes:
    return make_sample_pdf()


@pytest.fixture(scope="session")
def sample_docx() -> bytes:
    return make_sample_docx()


@pytest.fixture(autouse=True)
def _isolated_providers(tmp_path):  # type: ignore[no-untyped-def]
    set_storage(LocalStorage(str(tmp_path / "storage")))
    set_llm(None)
    yield
    set_storage(None)
    set_llm(None)


@pytest_asyncio.fixture(scope="session")
async def engine():  # type: ignore[no-untyped-def]
    from app.database.session import dispose_engine, get_engine, init_engine

    init_engine(os.environ["DATABASE_URL"])
    eng = get_engine()
    try:
        async with eng.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
    except OSError as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL not available: {exc}")
    yield eng
    await dispose_engine()


@pytest_asyncio.fixture
async def session_factory(engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:  # type: ignore[no-untyped-def]
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        yield s
        await s.rollback()


@pytest.fixture(scope="session")
def dispatcher(engine):  # type: ignore[no-untyped-def]
    """One Dispatcher per test session (aiogram routers can be attached only once)."""
    from app.bot.factory import create_dispatcher

    return create_dispatcher(async_sessionmaker(engine, expire_on_commit=False))
