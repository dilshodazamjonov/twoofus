from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.enums import MemberRole, sql_in


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored lower-case; uniqueness is therefore case-insensitive.
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(String(255))
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Room(Base):
    """The private space shared by the (at most) two members.

    A deployment hosts exactly one room: ``singleton`` is unique and must be 1,
    so even two concurrent owner-bootstrap attempts cannot create a second one.
    """

    __tablename__ = "rooms"
    __table_args__ = (CheckConstraint("singleton = 1", name="single_room"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    singleton: Mapped[int] = mapped_column(Integer, default=1, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RoomMember(Base):
    """Membership. ``(room_id, slot)`` is the primary key and ``slot`` may only be
    1 or 2, so the database itself guarantees a room never has more than two
    members, even under concurrent invitation acceptance."""

    __tablename__ = "room_members"
    __table_args__ = (
        CheckConstraint("slot IN (1, 2)", name="slot_range"),
        CheckConstraint(f"role IN ({sql_in(MemberRole)})", name="role_valid"),
        Index(
            "uq_room_members_one_owner",
            "room_id",
            unique=True,
            sqlite_where=text("role = 'owner'"),
            postgresql_where=text("role = 'owner'"),
        ),
    )

    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True
    )
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    role: Mapped[str] = mapped_column(String(16))
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
