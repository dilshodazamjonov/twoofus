from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import OutModel


class TulipOut(OutModel):
    id: uuid.UUID
    direction: Literal["sent", "received"]
    created_at: datetime
    is_new: bool = Field(
        description="Received and not yet seen by you. Never revealed to the sender."
    )


class TulipsOut(OutModel):
    items: list[TulipOut] = Field(description="Newest first.")
    unseen_count: int
