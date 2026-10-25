from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel, OutModel

PlaybackStatusLiteral = Literal[
    "playing", "paused", "idle", "not_connected", "private", "unavailable", "error"
]
ProviderLiteral = Literal["spotify", "yandex", "demo"]


class InvitationCreatedOut(OutModel):
    invite_url: str
    token: str = Field(description="Shown once. Only its hash is stored.")
    expires_at: datetime


class InvitationStatusOut(OutModel):
    pending: bool
    created_at: datetime | None = None
    expires_at: datetime | None = None


class InvitationTokenIn(ApiModel):
    token: str = Field(min_length=16, max_length=256)


class InvitationInspectOut(OutModel):
    app_name: str
    inviter_display_name: str
    expires_at: datetime


class InvitationAcceptIn(ApiModel):
    token: str = Field(min_length=16, max_length=256)
    username: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=10, max_length=256)


class MemberOut(OutModel):
    id: uuid.UUID
    display_name: str
    role: Literal["owner", "partner"]
    is_me: bool
    joined_at: datetime
    sharing_enabled: bool
    provider: ProviderLiteral | None = Field(
        description="Only revealed for yourself, or for a partner who is sharing."
    )


class RoomOut(OutModel):
    id: uuid.UUID
    app_name: str
    capacity: int = 2
    members: list[MemberOut]
    invitation: InvitationStatusOut | None = Field(
        default=None, description="Owner only: the pending invitation, if any."
    )


class PlaybackOut(OutModel):
    source: ProviderLiteral | None
    status: PlaybackStatusLiteral
    detail_code: str | None = Field(
        description="Machine-readable reason, e.g. sharing_off, nothing_playing, "
        "provider_reauth_required, provider_rate_limited, non_music_content."
    )
    content_type: Literal["track", "local_track", "episode", "ad", "other"] | None
    track_title: str | None
    artist_names: list[str]
    album: str | None
    artwork_url: str | None
    track_url: str | None = Field(description="Link-out to the track in its own service.")
    duration_ms: int | None
    progress_ms: int | None = Field(description="Position at fetched_at; null when unknown/stale.")
    is_playing: bool | None
    fetched_at: datetime | None = Field(description="When the provider was actually asked.")
    last_changed_at: datetime | None = Field(
        description="When this server first saw the current state; null until a change is seen."
    )
    is_stale: bool
    is_demo: bool
    experimental: bool


class MemberNowPlayingOut(OutModel):
    user_id: uuid.UUID
    display_name: str
    is_me: bool
    sharing_enabled: bool
    playback: PlaybackOut


class RoomNowPlayingOut(OutModel):
    generated_at: datetime
    poll_after_seconds: int
    me: MemberNowPlayingOut
    partner: MemberNowPlayingOut | None
    partner_joined: bool
