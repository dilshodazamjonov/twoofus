"""The two-person now-playing view.

Policy:

* Consent first: a partner who is not sharing is answered with ``private``
  before any provider is contacted; nothing about them is fetched or cached.
* One upstream call per connection per TTL (15-60 s, default 20 s). Requests
  arriving meanwhile, from either member, are served from the cache.
* Single flight: concurrent requests for the same connection wait for one
  in-flight fetch instead of issuing their own.
* Failures back off (Retry-After when the provider sends it, otherwise
  exponential from 15 s up to 5 min). During backoff the last good state is
  served for at most 5 minutes, flagged ``is_stale`` and without progress.
* The cache lives in process memory only. Playback content is never written to
  the database; only fetch timestamps and health codes are.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.crypto import DecryptionError, TokenCipher
from app.models import ConnectionStatus, ProviderConnection, ProviderName
from app.providers.base import (
    ContentType,
    Credentials,
    PlaybackProvider,
    PlaybackStatus,
    ProviderError,
    ProviderPlayback,
    TokenSet,
    TrackInfo,
)
from app.providers.registry import ProviderRegistry
from app.services.credentials import token_context
from app.services.members import ConnectionRef, MemberInfo, RoomMembers

logger = logging.getLogger(__name__)

MAX_STALE = timedelta(minutes=5)
BASE_BACKOFF_SECONDS = 15.0
MAX_BACKOFF_SECONDS = 300.0
TRANSIENT_CODES = frozenset(
    {"provider_unreachable", "provider_rate_limited", "provider_quota_exceeded", "provider_backoff"}
)


@dataclass(frozen=True, slots=True)
class PlaybackView:
    source: str | None
    status: PlaybackStatus
    detail_code: str | None = None
    content_type: ContentType | None = None
    track: TrackInfo | None = None
    progress_ms: int | None = None
    is_playing: bool | None = None
    fetched_at: datetime | None = None
    last_changed_at: datetime | None = None
    is_stale: bool = False
    is_demo: bool = False
    experimental: bool = False


@dataclass(frozen=True, slots=True)
class MemberPlayback:
    member: MemberInfo
    is_me: bool
    playback: PlaybackView


@dataclass(frozen=True, slots=True)
class RoomNowPlaying:
    generated_at: datetime
    poll_after_seconds: int
    me: MemberPlayback
    partner: MemberPlayback | None


@dataclass(slots=True)
class _Entry:
    playback: ProviderPlayback
    fetched_at: datetime
    last_changed_at: datetime | None
    refresh_due: bool = False


@dataclass(frozen=True, slots=True)
class _Flags:
    source: str
    is_demo: bool
    experimental: bool


class NowPlayingService:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: ProviderRegistry,
        cipher: TokenCipher,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
    ) -> None:
        self._settings = settings
        self._providers = providers
        self._cipher = cipher
        self._session_factory = session_factory
        self._clock = clock
        self._entries: dict[uuid.UUID, _Entry] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}
        self.upstream_calls = 0  # observability / tests

    @property
    def ttl(self) -> timedelta:
        return timedelta(seconds=self._settings.now_playing_ttl_seconds)

    def evict(self, connection_id: uuid.UUID) -> None:
        self._entries.pop(connection_id, None)

    def invalidate(self, connection_id: uuid.UUID) -> None:
        """Refresh on the next request, but keep the last state for stale display."""
        entry = self._entries.get(connection_id)
        if entry is not None:
            entry.refresh_due = True

    # ----- public API -----------------------------------------------------

    async def room_view(self, members: RoomMembers) -> RoomNowPlaying:
        if members.partner is not None:
            me, partner = await asyncio.gather(
                self._member_view(members.me, is_me=True),
                self._member_view(members.partner, is_me=False),
            )
        else:
            me, partner = await self._member_view(members.me, is_me=True), None
        return RoomNowPlaying(
            generated_at=self._clock(),
            poll_after_seconds=self._settings.now_playing_ttl_seconds,
            me=me,
            partner=partner,
        )

    async def _member_view(self, member: MemberInfo, *, is_me: bool) -> MemberPlayback:
        if not is_me and not member.sharing_enabled:
            view = PlaybackView(
                source=None, status=PlaybackStatus.PRIVATE, detail_code="sharing_off"
            )
        elif member.connection is None:
            view = PlaybackView(
                source=None, status=PlaybackStatus.NOT_CONNECTED, detail_code="not_connected"
            )
        else:
            view = await self.playback_for(member.connection)
        return MemberPlayback(member=member, is_me=is_me, playback=view)

    async def playback_for(self, conn: ConnectionRef) -> PlaybackView:
        provider = self._providers.get(conn.provider)
        flags = _Flags(
            source=conn.provider,
            is_demo=conn.provider == ProviderName.DEMO.value,
            experimental=conn.provider == ProviderName.YANDEX.value,
        )
        if conn.status == ConnectionStatus.REAUTH_REQUIRED.value:
            return self._error(flags, "provider_reauth_required")
        if provider is None:
            return self._error(flags, "provider_not_configured", PlaybackStatus.UNAVAILABLE)

        lock = self._locks.setdefault(conn.id, asyncio.Lock())
        async with lock:
            entry = self._entries.get(conn.id)
            if (
                entry is not None
                and not entry.refresh_due
                and self._clock() - entry.fetched_at < self.ttl
            ):
                return self._fresh(entry, flags)
            return await self._refresh(conn.id, provider, entry, flags)

    # ----- internals ------------------------------------------------------

    async def _refresh(
        self,
        connection_id: uuid.UUID,
        provider: PlaybackProvider,
        entry: _Entry | None,
        flags: _Flags,
    ) -> PlaybackView:
        async with self._session_factory() as db:
            row = await db.get(ProviderConnection, connection_id)
            if row is None:  # disconnected in the meantime
                self.evict(connection_id)
                return PlaybackView(
                    source=None, status=PlaybackStatus.NOT_CONNECTED, detail_code="not_connected"
                )
            if row.status == ConnectionStatus.REAUTH_REQUIRED.value:
                return self._error(flags, "provider_reauth_required")
            now = self._clock()
            if row.backoff_until is not None and row.backoff_until > now:
                return self._degraded(entry, flags, row.last_error_code or "provider_backoff", now)

            try:
                credentials = self._credentials(row)
            except DecryptionError:
                return await self._record_failure(
                    db,
                    row,
                    ProviderError("provider_reauth_required", reauth_required=True),
                    entry,
                    flags,
                )

            row.last_fetch_at = now
            self.upstream_calls += 1
            try:
                async with asyncio.timeout(self._settings.provider_timeout_seconds * 2 + 2):
                    result = await provider.fetch_playback(credentials, subject_key=str(row.id))
            except ProviderError as exc:
                return await self._record_failure(db, row, exc, entry, flags)
            except TimeoutError:
                return await self._record_failure(
                    db, row, ProviderError("provider_unreachable"), entry, flags
                )
            except Exception as exc:
                logger.error("unexpected %s provider failure: %s", row.provider, type(exc).__name__)
                return await self._record_failure(
                    db, row, ProviderError("provider_bad_response"), entry, flags
                )

            fetched_at = self._clock()
            if result.new_tokens is not None:
                self._store_tokens(row, result.new_tokens)
            row.last_success_at = fetched_at
            row.last_error_code = None
            row.consecutive_failures = 0
            row.backoff_until = None
            await db.commit()

        if entry is None:
            last_changed = None  # we have not seen a change yet: unknown, not "now"
        elif entry.playback.identity() != result.playback.identity():
            last_changed = fetched_at
        else:
            last_changed = entry.last_changed_at
        new_entry = _Entry(result.playback, fetched_at, last_changed)
        self._entries[connection_id] = new_entry
        return self._fresh(new_entry, flags)

    def _credentials(self, row: ProviderConnection) -> Credentials:
        def dec(value: str | None, field: str) -> str | None:
            if value is None:
                return None
            return self._cipher.decrypt(
                value, context=token_context(row.user_id, row.provider, field)
            )

        return Credentials(
            access_token=dec(row.access_token_enc, "access"),
            refresh_token=dec(row.refresh_token_enc, "refresh"),
            expires_at=row.token_expires_at,
        )

    def _store_tokens(self, row: ProviderConnection, tokens: TokenSet) -> None:
        row.access_token_enc = self._cipher.encrypt(
            tokens.access_token, context=token_context(row.user_id, row.provider, "access")
        )
        if tokens.refresh_token:
            row.refresh_token_enc = self._cipher.encrypt(
                tokens.refresh_token, context=token_context(row.user_id, row.provider, "refresh")
            )
        row.token_expires_at = tokens.expires_at
        if tokens.scopes:
            row.scopes = tokens.scopes
        row.token_version += 1

    async def _record_failure(
        self,
        db: AsyncSession,
        row: ProviderConnection,
        exc: ProviderError,
        entry: _Entry | None,
        flags: _Flags,
    ) -> PlaybackView:
        now = self._clock()
        row.last_error_code = exc.code
        row.last_error_at = now
        row.consecutive_failures += 1
        if exc.reauth_required:
            row.status = ConnectionStatus.REAUTH_REQUIRED.value
            row.reauth_required_at = now
            await db.commit()
            self.evict(row.id)
            logger.info("%s connection needs re-authorisation", row.provider)
            return self._error(flags, "provider_reauth_required")
        delay = (
            exc.retry_after_seconds
            if exc.retry_after_seconds is not None
            else min(
                BASE_BACKOFF_SECONDS * 2 ** (row.consecutive_failures - 1), MAX_BACKOFF_SECONDS
            )
        )
        row.backoff_until = now + timedelta(seconds=delay)
        await db.commit()
        logger.info("%s fetch failed: %s (backing off %.0fs)", row.provider, exc.code, delay)
        return self._degraded(entry, flags, exc.code, now)

    def _fresh(self, entry: _Entry, flags: _Flags) -> PlaybackView:
        p = entry.playback
        return PlaybackView(
            source=flags.source,
            status=p.status,
            detail_code=p.detail_code,
            content_type=p.content_type,
            track=p.track,
            progress_ms=p.progress_ms,
            is_playing=p.is_playing,
            fetched_at=entry.fetched_at,
            last_changed_at=entry.last_changed_at,
            is_stale=False,
            is_demo=flags.is_demo,
            experimental=flags.experimental,
        )

    def _degraded(
        self, entry: _Entry | None, flags: _Flags, code: str, now: datetime
    ) -> PlaybackView:
        if entry is not None and now - entry.fetched_at <= MAX_STALE:
            p = entry.playback
            return PlaybackView(
                source=flags.source,
                status=p.status,
                detail_code=code,
                content_type=p.content_type,
                track=p.track,
                progress_ms=None,  # never extrapolate progress from stale data
                is_playing=p.is_playing,
                fetched_at=entry.fetched_at,
                last_changed_at=entry.last_changed_at,
                is_stale=True,
                is_demo=flags.is_demo,
                experimental=flags.experimental,
            )
        status = PlaybackStatus.UNAVAILABLE if code in TRANSIENT_CODES else PlaybackStatus.ERROR
        return self._error(flags, code, status)

    @staticmethod
    def _error(
        flags: _Flags, code: str, status: PlaybackStatus = PlaybackStatus.ERROR
    ) -> PlaybackView:
        return PlaybackView(
            source=flags.source,
            status=status,
            detail_code=code,
            is_demo=flags.is_demo,
            experimental=flags.experimental,
        )
