from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import CandidateProfile


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_full(self, user_id: int) -> CandidateProfile | None:
        return await self.session.scalar(
            select(CandidateProfile)
            .where(CandidateProfile.user_id == user_id)
            .options(
                selectinload(CandidateProfile.experiences),
                selectinload(CandidateProfile.education),
                selectinload(CandidateProfile.skills),
                selectinload(CandidateProfile.languages),
                selectinload(CandidateProfile.portfolios),
            )
            .execution_options(populate_existing=True)
        )

    async def get_or_create(self, user_id: int) -> CandidateProfile:
        profile = await self.get_full(user_id)
        if profile is None:
            profile = CandidateProfile(user_id=user_id)
            self.session.add(profile)
            await self.session.flush()
            profile = await self.get_full(user_id)
            assert profile is not None
        return profile
