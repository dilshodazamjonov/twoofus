"""Provider-neutral playback contract shared by every music adapter.

Adapters translate their service's response into :class:`ProviderPlayback`
and report failures as :class:`ProviderError`. They never touch the database:
refreshed credentials are handed back in :class:`FetchResult` for the service
layer to encrypt and persist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.models.enums import ProviderName


class PlaybackStatus(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"
    NOT_CONNECTED = "not_connected"
    PRIVATE = "private"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ContentType(StrEnum):
    TRACK = "track"
    LOCAL_TRACK = "local_track"
    EPISODE = "episode"
    AD = "ad"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class TrackInfo:
    title: str
    artist_names: tuple[str, ...] = ()
    album: str | None = None
    artwork_url: str | None = None
    track_url: str | None = None
    duration_ms: int | None = None
    # Used only to detect track changes; never exposed through the API.
    provider_track_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderPlayback:
    """What a provider actually reported. Adapters only ever produce
    PLAYING, PAUSED, IDLE or PRIVATE here; other statuses are decided by the
    service layer (consent, connection state, errors)."""

    status: PlaybackStatus
    content_type: ContentType | None = None
    track: TrackInfo | None = None
    progress_ms: int | None = None
    detail_code: str | None = None

    @property
    def is_playing(self) -> bool | None:
        if self.status is PlaybackStatus.PLAYING:
            return True
        if self.status in (PlaybackStatus.PAUSED, PlaybackStatus.IDLE):
            return False
        return None

    def identity(self) -> tuple[object, ...]:
        """What counts as "the playback changed" for ``last_changed_at``."""
        track = self.track
        key = (track.provider_track_id or track.title, track.artist_names) if track else None
        return (self.status, self.content_type, key)


@dataclass(frozen=True, slots=True)
class Credentials:
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    playback: ProviderPlayback
    new_tokens: TokenSet | None = None


class ProviderError(Exception):
    """A provider call failed. ``code`` is a stable, user-explainable reason.

    Codes: provider_reauth_required, provider_forbidden, provider_rate_limited,
    provider_quota_exceeded, provider_unreachable, provider_bad_response,
    provider_not_configured.
    """

    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        retry_after_seconds: float | None = None,
        reauth_required: bool = False,
    ) -> None:
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        self.reauth_required = reauth_required
        super().__init__(message or code)


class PlaybackProvider(Protocol):
    name: ProviderName
    experimental: bool

    async def fetch_playback(self, credentials: Credentials, *, subject_key: str) -> FetchResult:
        """Read the current playback. ``subject_key`` is a stable, non-secret
        identifier of the connection (used by the demo provider and Ynison)."""
        ...
