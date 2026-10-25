"""The per-user "Share my now-playing" consent switch."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.config import SHARING_NOTICE_VERSION
from app.core.errors import AppError
from app.models import SharePreference


class NoticeNotAcknowledged(AppError):
    status_code = 409
    code = "sharing_notice_not_acknowledged"
    message = "Please read and acknowledge what sharing means before turning it on."


async def get_preference(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> SharePreference:
    pref = (
        await db.execute(select(SharePreference).where(SharePreference.user_id == user_id))
    ).scalar_one_or_none()
    if pref is None:  # defensive: every account gets a row at creation
        pref = SharePreference(user_id=user_id, share_now_playing=False, updated_at=ctx.clock())
        db.add(pref)
        await db.commit()
    return pref


async def set_sharing(
    db: AsyncSession,
    ctx: AppContext,
    user_id: uuid.UUID,
    *,
    enabled: bool,
    acknowledged_notice_version: str | None,
) -> SharePreference:
    pref = await get_preference(db, ctx, user_id)
    now = ctx.clock()
    if enabled:
        if acknowledged_notice_version != SHARING_NOTICE_VERSION:
            raise NoticeNotAcknowledged
        if pref.notice_version_acknowledged != SHARING_NOTICE_VERSION:
            pref.notice_version_acknowledged = SHARING_NOTICE_VERSION
            pref.acknowledged_at = now
    pref.share_now_playing = enabled
    pref.updated_at = now
    await db.commit()
    return pref
