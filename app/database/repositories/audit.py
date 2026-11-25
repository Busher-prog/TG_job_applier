from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLog


async def audit(
    session: AsyncSession,
    action: str,
    *,
    user_id: int | None = None,
    actor: str = "user",
    entity_type: str | None = None,
    entity_id: object | None = None,
    **meta: Any,
) -> None:
    """Append an audit entry. ``meta`` must not contain personal data or secrets."""
    session.add(
        AuditLog(
            user_id=user_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            meta=meta,
        )
    )
