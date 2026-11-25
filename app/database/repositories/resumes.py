from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Resume, ResumeVersion


class ResumeRepository:
    """All queries are scoped by user_id to enforce data isolation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: int) -> list[Resume]:
        rows = await self.session.scalars(
            select(Resume).where(Resume.user_id == user_id).order_by(Resume.created_at.desc(), Resume.id.desc())
        )
        return list(rows)

    async def get_for_user(self, user_id: int, resume_id: int) -> Resume | None:
        return await self.session.scalar(
            select(Resume)
            .where(Resume.id == resume_id, Resume.user_id == user_id)
            .options(selectinload(Resume.versions))
        )

    async def get_primary(self, user_id: int) -> Resume | None:
        return await self.session.scalar(
            select(Resume).where(Resume.user_id == user_id, Resume.is_primary.is_(True)).limit(1)
        )

    async def set_primary(self, user_id: int, resume_id: int) -> None:
        await self.session.execute(
            update(Resume).where(Resume.user_id == user_id).values(is_primary=(Resume.id == resume_id))
        )

    async def get_version_for_user(self, user_id: int, version_id: int) -> ResumeVersion | None:
        return await self.session.scalar(
            select(ResumeVersion)
            .join(Resume, Resume.id == ResumeVersion.resume_id)
            .where(ResumeVersion.id == version_id, Resume.user_id == user_id)
        )
