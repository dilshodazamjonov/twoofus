from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel, OutModel


class ProfileIn(ApiModel):
    display_name: str = Field(min_length=1, max_length=40)


class SharingIn(ApiModel):
    share_now_playing: bool
    acknowledged_notice_version: str | None = Field(
        default=None,
        max_length=32,
        description="Required when turning sharing on; must equal the current notice version.",
    )


class SharingOut(OutModel):
    share_now_playing: bool
    current_notice_version: str
    notice_version_acknowledged: str | None
    acknowledged_at: datetime | None
    updated_at: datetime


class DeleteAccountIn(ApiModel):
    password: str = Field(min_length=1, max_length=256)


class SessionInfoOut(OutModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = Field(description="The session making this request.")


class SessionsOut(OutModel):
    sessions: list[SessionInfoOut] = Field(description="Most recently used first.")


class RevokedOut(OutModel):
    revoked: int
