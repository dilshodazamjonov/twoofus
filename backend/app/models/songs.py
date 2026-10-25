from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.types import UTCDateTime


class TrackSnapshot:
    """A song as the member's music service described it when they chose it.

    Copied from their own recently played list (app/services/songs.py), never
    typed or pasted by a user, so links and covers point at the service.
    """

    provider: Mapped[str] = mapped_column(String(16))
    track_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    artist_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    artwork_url: Mapped[str | None] = mapped_column(String(500), default=None)
    track_url: Mapped[str | None] = mapped_column(String(500), default=None)


class SongPick(TrackSnapshot, Base):
    """The one song a member picked for the other. A new pick replaces it."""

    __tablename__ = "song_picks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PlaylistItem(TrackSnapshot, Base):
    """A song on the room's shared playlist (at most 50, no repeats)."""

    __tablename__ = "playlist_items"
    __table_args__ = (UniqueConstraint("room_id", "provider", "track_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    added_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DailyAnswer(Base):
    """A member's answer to the question of the (UTC) day. Kept for 7 days."""

    __tablename__ = "daily_answers"
    __table_args__ = (UniqueConstraint("user_id", "day"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date)
    answer: Mapped[str] = mapped_column(String(140))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
