from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ConsentRecord, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def create(self, **fields: object) -> User:
        user = User(**fields)
        self.session.add(user)
        await self.session.flush()
        return user

    async def touch(self, user: User) -> None:
        user.last_active_at = datetime.now(UTC)

    async def latest_consent(self, user_id: int, consent_type: str) -> ConsentRecord | None:
        return await self.session.scalar(
            select(ConsentRecord)
            .where(ConsentRecord.user_id == user_id, ConsentRecord.consent_type == consent_type)
            .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
            .limit(1)
        )

    async def add_consent(
        self, user_id: int, consent_type: str, version: str, granted: bool, language: str | None
    ) -> ConsentRecord:
        record = ConsentRecord(
            user_id=user_id,
            consent_type=consent_type,
            document_version=version,
            granted=granted,
            language=language,
        )
        self.session.add(record)
        await self.session.flush()
        return record
