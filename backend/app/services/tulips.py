"""Tulips: a small signal from one member to the other.

* Nothing user-written is stored, so nothing can be injected into the other
  screen.
* Retention: at most ``MAX_PER_ROOM`` per room and nothing older than
  ``RETENTION``. Enforced on every send and by the hourly cleanup.
* No read receipts: ``seen_at`` only drives the recipient's own "new" state
  and is never shown to the sender.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import Conflict
from app.models import RoomMember, Tulip
from app.services.members import load_room_members

RETENTION = timedelta(days=7)
MAX_PER_ROOM = 20


class NoPartner(Conflict):
    code = "no_partner"
    message = "Nobody else has joined yet."


@dataclass(frozen=True, slots=True)
class TulipView:
    id: uuid.UUID
    direction: Literal["sent", "received"]
    created_at: datetime
    is_new: bool


@dataclass(frozen=True, slots=True)
class TulipsView:
    items: list[TulipView]
    unseen_count: int


def _view(tulip: Tulip, user_id: uuid.UUID) -> TulipView:
    received = tulip.recipient_id == user_id
    return TulipView(
        id=tulip.id,
        direction="received" if received else "sent",
        created_at=tulip.created_at,
        is_new=received and tulip.seen_at is None,
    )


async def send_tulip(db: AsyncSession, ctx: AppContext, *, sender_id: uuid.UUID) -> TulipView:
    members = await load_room_members(db, sender_id)
    if members.partner is None:
        raise NoPartner
    now = ctx.clock()
    tulip = Tulip(
        id=uuid.uuid4(),
        room_id=members.room_id,
        sender_id=sender_id,
        recipient_id=members.partner.user.id,
        created_at=now,
    )
    db.add(tulip)
    await db.flush()
    await _prune_room(db, members.room_id, now)
    await db.commit()
    return _view(tulip, sender_id)


async def _prune_room(db: AsyncSession, room_id: uuid.UUID, now: datetime) -> None:
    await db.execute(
        delete(Tulip).where(Tulip.room_id == room_id, Tulip.created_at < now - RETENTION)
    )
    newest = (
        select(Tulip.id)
        .where(Tulip.room_id == room_id)
        .order_by(Tulip.created_at.desc(), Tulip.id.desc())
        .limit(MAX_PER_ROOM)
    )
    await db.execute(delete(Tulip).where(Tulip.room_id == room_id, Tulip.id.not_in(newest)))


async def recent_tulips(db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID) -> TulipsView:
    room_id = (
        await db.execute(select(RoomMember.room_id).where(RoomMember.user_id == user_id))
    ).scalar_one()
    since = ctx.clock() - RETENTION
    mine = (
        Tulip.room_id == room_id,
        or_(Tulip.sender_id == user_id, Tulip.recipient_id == user_id),
        Tulip.created_at >= since,
    )
    rows = await db.execute(
        select(Tulip)
        .where(*mine)
        .order_by(Tulip.created_at.desc(), Tulip.id.desc())
        .limit(MAX_PER_ROOM)
    )
    unseen = (
        await db.execute(
            select(func.count())
            .select_from(Tulip)
            .where(*mine, Tulip.recipient_id == user_id, Tulip.seen_at.is_(None))
        )
    ).scalar_one()
    return TulipsView(items=[_view(t, user_id) for t in rows.scalars()], unseen_count=int(unseen))


async def mark_seen(db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Tulip)
        .where(Tulip.recipient_id == user_id, Tulip.seen_at.is_(None))
        .values(seen_at=ctx.clock())
    )
    await db.commit()


async def purge_expired_tulips(db: AsyncSession, now: datetime) -> None:
    await db.execute(delete(Tulip).where(Tulip.created_at < now - RETENTION))
