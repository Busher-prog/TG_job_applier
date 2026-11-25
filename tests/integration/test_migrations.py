"""Alembic migrations apply cleanly and match the ORM models."""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "ALEMBIC_DATABASE_URL": url}
    return subprocess.run([sys.executable, "-m", "alembic", *args], capture_output=True, text=True, env=env,
                          cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


async def test_upgrade_downgrade_and_no_drift(engine):  # type: ignore[no-untyped-def]
    from sqlalchemy import text

    url = os.environ["DATABASE_URL"]
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    try:
        up = _alembic("upgrade", "head", url=url)
        assert up.returncode == 0, up.stderr
        check = _alembic("check", url=url)
        assert check.returncode == 0, check.stdout + check.stderr
        down = _alembic("downgrade", "base", url=url)
        assert down.returncode == 0, down.stderr
        assert _alembic("upgrade", "head", url=url).returncode == 0
    finally:
        # Restore the schema expected by other tests (create_all is idempotent with migrations).
        from app.database.models import Base

        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
