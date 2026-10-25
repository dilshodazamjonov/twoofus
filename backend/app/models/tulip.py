from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.types import UTCDateTime


class Tulip(Base):
    """A tulip sent from one member to the other.

    Only sender, recipient and two timestamps are stored. The service keeps at
    most 20 per room and deletes them after 7 days. ``seen_at`` is only ever
    shown to the recipient (no read receipts).
    """

    __tablename__ = "tulips"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
