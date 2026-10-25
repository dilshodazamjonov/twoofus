"""Read-side helpers for the room and its (at most two) members."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MemberRole, ProviderConnection, RoomMember, SharePreference, User


@dataclass(frozen=True, slots=True)
class ConnectionRef:
    """Plain snapshot of a provider connection (safe to pass across sessions)."""

    id: uuid.UUID
    provider: str
    status: str
    token_version: int


@dataclass(frozen=True, slots=True)
class MemberInfo:
    user: User
    membership: RoomMember
    sharing_enabled: bool
    connection: ConnectionRef | None

    @property
    def is_owner(self) -> bool:
        return self.membership.role == MemberRole.OWNER.value


@dataclass(frozen=True, slots=True)
class RoomMembers:
    room_id: uuid.UUID
    me: MemberInfo
    partner: MemberInfo | None


async def load_room_members(db: AsyncSession, user_id: uuid.UUID) -> RoomMembers:
    room_id = (
        await db.execute(select(RoomMember.room_id).where(RoomMember.user_id == user_id))
    ).scalar_one()
    rows = (
        await db.execute(
            select(RoomMember, User, SharePreference, ProviderConnection)
            .join(User, User.id == RoomMember.user_id)
            .outerjoin(SharePreference, SharePreference.user_id == User.id)
            .outerjoin(ProviderConnection, ProviderConnection.user_id == User.id)
            .where(RoomMember.room_id == room_id)
            .order_by(RoomMember.slot)
        )
    ).all()

    me: MemberInfo | None = None
    partner: MemberInfo | None = None
    for membership, user, pref, conn in rows:
        info = MemberInfo(
            user=user,
            membership=membership,
            sharing_enabled=bool(pref and pref.share_now_playing),
            connection=(
                ConnectionRef(conn.id, conn.provider, conn.status, conn.token_version)
                if conn is not None
                else None
            ),
        )
        if user.id == user_id:
            me = info
        else:
            partner = info
    if me is None:  # pragma: no cover - membership row was just read
        raise LookupError("membership disappeared")
    return RoomMembers(room_id=room_id, me=me, partner=partner)
