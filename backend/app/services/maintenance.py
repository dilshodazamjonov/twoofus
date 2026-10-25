"""Periodic cleanup of expired rows (sessions, auth flows, invitations, tulips)."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.models import AuthFlowStatus, AuthSession, Invitation, ProviderAuthFlow
from app.services.tulips import purge_expired_tulips

logger = logging.getLogger(__name__)

_GRACE = timedelta(days=7)
CLEANUP_INTERVAL_SECONDS = 3600


async def purge_expired(db: AsyncSession, clock: Clock) -> None:
    now = clock()
    cutoff = now - _GRACE
    await db.execute(
        delete(AuthSession).where(
            or_(AuthSession.expires_at < cutoff, AuthSession.revoked_at < cutoff)
        )
    )
    await db.execute(
        delete(ProviderAuthFlow).where(
            or_(
                ProviderAuthFlow.expires_at < now - timedelta(days=1),
                ProviderAuthFlow.status != AuthFlowStatus.PENDING.value,
            ),
            ProviderAuthFlow.created_at < now - timedelta(days=1),
        )
    )
    await db.execute(
        delete(Invitation).where(
            or_(
                Invitation.expires_at < cutoff,
                Invitation.consumed_at < cutoff,
                Invitation.revoked_at < cutoff,
            )
        )
    )
    await purge_expired_tulips(db, now)
    await db.commit()


async def cleanup_loop(session_factory: async_sessionmaker[AsyncSession], clock: Clock) -> None:
    while True:
        try:
            async with session_factory() as db:
                await purge_expired(db, clock)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep the loop alive; log type only
            logger.warning("cleanup failed: %s", type(exc).__name__)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
