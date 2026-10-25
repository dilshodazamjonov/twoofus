"""Yandex Music adapter. EXPERIMENTAL and UNOFFICIAL.

Yandex publishes no public API for this. The adapter relies on the community
``yandex-music`` package (MarshalX/yandex-music-api, pinned to 3.2.2), which
reverse-engineers private endpoints and can break whenever Yandex changes
them. Everything here is therefore flagged ``experimental`` and every failure
is reported to the user instead of being papered over.

What is used, and nothing else:

* OAuth device flow on oauth.yandex.ru (documented by Yandex ID:
  https://yandex.ru/dev/id/doc/en/codes/screen-code-oauth): the user approves
  on Yandex's own page; we never see her password. Requests go through our own
  HTTP client with the library's public Yandex Music app credentials.
* Token revocation (``/revoke_token``, documented by Yandex ID for tokens
  issued with a ``device_id``) on disconnect and account deletion.
* Ynison, read only: connect, read the player state, disconnect. The library's
  handshake registers a *remote-control, non-player* device with
  ``is_currently_active=False``; no pause/next/volume/queue command is sent.
* ``tracks([id])`` for title/artists/album of the current track only.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from app.models.enums import ProviderName
from app.providers.base import (
    ContentType,
    Credentials,
    FetchResult,
    PlaybackStatus,
    ProviderError,
    ProviderPlayback,
    TrackInfo,
)
from app.providers.urls import YANDEX_ARTWORK_HOSTS, YANDEX_LINK_HOSTS, safe_https_url

if TYPE_CHECKING:
    from yandex_music.ynison import YnisonClientAsync

# Fixed upstream hosts (test fakes can replace them only outside production).
OAUTH_BASE = "https://oauth.yandex.ru"

_NUMERIC_ID = re.compile(r"\d{1,20}")
_META_TTL_SECONDS = 6 * 3600
_META_FAILURE_TTL_SECONDS = 60
_META_MAX_ENTRIES = 512


# ----- gateway data types (library-independent) ------------------------------


@dataclass(frozen=True, slots=True)
class DeviceCode:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class YandexToken:
    access_token: str
    expires_in: int | None


@dataclass(frozen=True, slots=True)
class YnisonPlayable:
    playable_id: str
    album_id: str | None
    kind: str  # "track" | "local_track" | "infinite" | "video_clip" | "unspecified"
    title: str | None
    cover_url: str | None


@dataclass(frozen=True, slots=True)
class YnisonSnapshot:
    has_active_device: bool
    paused: bool
    progress_ms: int | None
    duration_ms: int | None
    playable: YnisonPlayable | None


@dataclass(frozen=True, slots=True)
class YandexTrackMeta:
    title: str | None
    artist_names: tuple[str, ...]
    album_title: str | None
    album_id: str | None
    cover_uri: str | None
    duration_ms: int | None


class DeviceFlowPending(Exception):
    """User has not approved yet (``authorization_pending`` / ``slow_down``)."""

    def __init__(self, *, slow_down: bool = False) -> None:
        self.slow_down = slow_down
        super().__init__("slow_down" if slow_down else "authorization_pending")


class DeviceFlowError(Exception):
    """Terminal device-flow failure. ``code`` is expired, denied or failed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class YandexGateway(Protocol):
    async def request_device_code(self, *, device_name: str, device_id: str) -> DeviceCode: ...

    async def poll_device_token(self, device_code: str) -> YandexToken | None: ...

    async def revoke_token(self, access_token: str) -> bool: ...

    async def fetch_player_state(
        self, access_token: str, *, device_id: str, device_title: str
    ) -> YnisonSnapshot: ...

    async def fetch_track(self, access_token: str, track_id: str) -> YandexTrackMeta | None: ...


# ----- real gateway: Yandex ID OAuth over httpx + the yandex-music package ----------


def music_app_credentials() -> tuple[str, str]:
    """The Yandex Music Android app's public OAuth client, as embedded in the
    pinned yandex-music library."""
    try:
        from yandex_music._client_async import device_auth

        return str(device_auth._DEFAULT_CLIENT_ID), str(device_auth._DEFAULT_CLIENT_SECRET)
    except (ImportError, AttributeError) as exc:  # the library changed shape
        raise ProviderError("provider_bad_response", "Yandex client data unavailable") from exc


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | str):
        try:
            number = int(value)
        except ValueError:
            return None
        return number if number > 0 else None
    return None


def _ynison_client_class(upstream_override: str | None) -> type[YnisonClientAsync]:
    from yandex_music.ynison import YnisonClientAsync

    if not upstream_override:
        return YnisonClientAsync
    # Local test fake only (a validated loopback URL, refused in production):
    # same library code, unencrypted WebSockets to the fake on 127.0.0.1.
    host = upstream_override.removeprefix("http://")
    scheme = "ws"  # loopback only; the real client keeps Yandex's wss:// URLs

    class _LocalFakeYnison(YnisonClientAsync):
        _BASE_URL = f"{scheme}://{host}/yandex/ynison"

        def _state_uri(self, redirect: Any) -> str:
            return f"{scheme}://{redirect.host}/{self._STATE_SERVICE}"

    return _LocalFakeYnison


class LibraryYandexGateway:
    """Yandex ID OAuth (device flow, revocation) over our own HTTP client, and
    the ``yandex-music`` 3.2.2 package for Ynison and track metadata. The
    package is imported lazily so the rest of the app never depends on it."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        http: httpx.AsyncClient,
        upstream_override: str | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._http = http
        self._oauth_base = f"{upstream_override}/yandex/oauth" if upstream_override else OAUTH_BASE
        self._api_base = f"{upstream_override}/yandex/api" if upstream_override else None
        self._upstream_override = upstream_override

    async def _oauth_post(self, path: str, form: dict[str, str]) -> httpx.Response:
        try:
            return await self._http.post(
                f"{self._oauth_base}{path}",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise ProviderError("provider_unreachable", f"Yandex OAuth {path} failed") from exc

    async def request_device_code(self, *, device_name: str, device_id: str) -> DeviceCode:
        client_id, _ = music_app_credentials()
        response = await self._oauth_post(
            "/device/code",
            {"client_id": client_id, "device_id": device_id, "device_name": device_name},
        )
        body = _json_object(response)
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError("provider_unreachable", f"device code: {response.status_code}")
        fields = body or {}
        device_code = fields.get("device_code")
        user_code = fields.get("user_code")
        verification_url = fields.get("verification_url")
        expires_in = _positive_int(fields.get("expires_in"))
        if (
            response.status_code != 200
            or not isinstance(device_code, str)
            or not device_code
            or not isinstance(user_code, str)
            or not user_code
            or not isinstance(verification_url, str)
            or expires_in is None
        ):
            raise ProviderError("provider_bad_response", "unexpected device code response")
        return DeviceCode(
            device_code=device_code,
            user_code=user_code,
            verification_url=verification_url,
            expires_in=expires_in,
            interval=_positive_int(fields.get("interval")) or 5,
        )

    async def poll_device_token(self, device_code: str) -> YandexToken | None:
        client_id, client_secret = music_app_credentials()
        response = await self._oauth_post(
            "/token",
            {
                "grant_type": "device_code",
                "code": device_code,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        body = _json_object(response) or {}
        if response.status_code == 200:
            access = body.get("access_token")
            if not isinstance(access, str) or not access:
                raise ProviderError("provider_bad_response", "token response without a token")
            return YandexToken(
                access_token=access, expires_in=_positive_int(body.get("expires_in"))
            )
        if response.status_code >= 500 or response.status_code == 429:
            raise ProviderError("provider_unreachable", f"device token: {response.status_code}")
        # Error names from Yandex ID's documentation, plus RFC 8628's.
        match body.get("error"):
            case "authorization_pending":
                return None
            case "slow_down":
                raise DeviceFlowPending(slow_down=True)
            case "expired_token" | "invalid_grant":
                raise DeviceFlowError("expired")
            case "access_denied":
                raise DeviceFlowError("denied")
            case _:
                raise DeviceFlowError("failed")

    async def revoke_token(self, access_token: str) -> bool:
        """Ask Yandex to invalidate the token. True only when Yandex confirms."""
        client_id, client_secret = music_app_credentials()
        try:
            response = await self._oauth_post(
                "/revoke_token",
                {
                    "access_token": access_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
        except ProviderError:
            return False
        return response.status_code == 200

    async def fetch_player_state(
        self, access_token: str, *, device_id: str, device_title: str
    ) -> YnisonSnapshot:
        from yandex_music.exceptions import (
            YandexMusicError,
            YnisonServerError,
            YnisonUnauthorizedError,
        )

        client = _ynison_client_class(self._upstream_override)(
            access_token,
            device_id=device_id,
            device_title=device_title,
            max_reconnect_attempts=1,
        )
        try:
            async with client.session(timeout=self._timeout) as connected:
                return snapshot_from_ynison_state(connected.state, int(time.time() * 1000))
        except YnisonUnauthorizedError as exc:
            raise ProviderError(
                "provider_reauth_required", "Ynison rejected the token", reauth_required=True
            ) from exc
        except YnisonServerError as exc:
            if exc.go_away_seconds:
                # "Go away for N seconds" also comes with a 503 ("temporary unavailable"),
                # e.g. for an account Ynison won't serve; only 429 means "slow down".
                limited = exc.http_code == 429 or exc.grpc_code == 8  # RESOURCE_EXHAUSTED
                raise ProviderError(
                    "provider_rate_limited" if limited else "provider_unreachable",
                    retry_after_seconds=float(exc.go_away_seconds),
                ) from exc
            backoff = max(exc.backoff_ms) / 1000 if exc.backoff_ms else None
            raise ProviderError("provider_unreachable", retry_after_seconds=backoff) from exc
        except (YandexMusicError, OSError, TimeoutError) as exc:
            raise ProviderError("provider_unreachable", "Ynison unavailable") from exc

    async def fetch_track(self, access_token: str, track_id: str) -> YandexTrackMeta | None:
        from yandex_music import ClientAsync
        from yandex_music.exceptions import UnauthorizedError, YandexMusicError

        try:
            async with asyncio.timeout(self._timeout):
                # No client.init(): it would fetch account details we do not need.
                tracks = await ClientAsync(access_token, base_url=self._api_base).tracks([track_id])
        except UnauthorizedError as exc:
            raise ProviderError(
                "provider_reauth_required", "track lookup unauthorized", reauth_required=True
            ) from exc
        except (TimeoutError, YandexMusicError):
            return None
        if not tracks:
            return None
        track = tracks[0]
        album = track.albums[0] if track.albums else None
        return YandexTrackMeta(
            title=track.title,
            artist_names=tuple(a.name for a in track.artists if a is not None and a.name),
            album_title=album.title if album is not None else None,
            album_id=str(album.id) if album is not None and album.id is not None else None,
            cover_uri=track.cover_uri or (album.cover_uri if album is not None else None),
            duration_ms=track.duration_ms,
        )


def snapshot_from_ynison_state(state: object, now_ms: int) -> YnisonSnapshot:
    """Reduce a ``PutYnisonStateResponse`` to the few fields we use."""
    from yandex_music.ynison import utils
    from yandex_music.ynison.models import ynison_state

    if not isinstance(state, ynison_state.PutYnisonStateResponse):
        # The unofficial library changed shape: report it, never guess.
        raise ProviderError("provider_bad_response", "unexpected Ynison state object")
    active = utils.get_active_device(state)
    has_active = active is not None and not active.is_offline
    current = utils.get_current_playable(state)
    status = state.player_state.status

    playable: YnisonPlayable | None = None
    if current is not None and current.playable_id:
        kind_names = {
            ynison_state.PlayablePlayableType.TRACK: "track",
            ynison_state.PlayablePlayableType.LOCAL_TRACK: "local_track",
            ynison_state.PlayablePlayableType.INFINITE: "infinite",
            ynison_state.PlayablePlayableType.VIDEO_CLIP: "video_clip",
        }
        playable = YnisonPlayable(
            playable_id=current.playable_id,
            album_id=current.album_id_optional or None,
            kind=kind_names.get(current.playable_type, "unspecified"),
            title=current.title or None,
            cover_url=current.cover_url_optional or None,
        )
    duration = status.duration_ms if status.duration_ms > 0 else None
    progress = utils.get_current_progress_ms(status, now_ms) if playable and has_active else None
    return YnisonSnapshot(
        has_active_device=has_active,
        paused=bool(status.paused),
        progress_ms=progress,
        duration_ms=duration,
        playable=playable,
    )


# ----- provider ---------------------------------------------------------------------


def yandex_cover_url(uri: str | None, size: str = "400x400") -> str | None:
    """Yandex cover URIs look like ``avatars.yandex.net/get-music-content/.../%%``."""
    if not uri:
        return None
    url = uri.strip().replace("%%", size)
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    elif not url.startswith("https://"):
        url = "https://" + url.lstrip("/")
    return safe_https_url(url, YANDEX_ARTWORK_HOSTS)


def ynison_device_id(subject_key: str) -> str:
    """Stable per-connection device id (12 hex chars, same shape as the library's)."""
    return hashlib.sha256(f"twoofus-ynison:{subject_key}".encode()).hexdigest()[:12]


def oauth_device_id(user_key: str) -> str:
    """Stable per-member OAuth ``device_id`` (6-50 printable chars per Yandex ID).

    Makes the token revocable (Yandex only revokes tokens issued for a device)
    and keeps one "JustTheTwoOfUs" entry in her Yandex ID device list instead
    of a new one per approval.
    """
    return "twoofus-" + hashlib.sha256(f"twoofus-oauth:{user_key}".encode()).hexdigest()[:24]


class YandexProvider:
    name = ProviderName.YANDEX
    experimental = True

    def __init__(
        self,
        gateway: YandexGateway,
        *,
        app_name: str,
        web_base: str,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._gateway = gateway
        self._device_title = f"{app_name} (read-only)"[:60]
        self._device_name = app_name[:60]
        self._web_base = web_base.rstrip("/")
        self._clock = clock
        self._monotonic = monotonic
        self._meta_cache: OrderedDict[str, tuple[float, YandexTrackMeta | None]] = OrderedDict()

    # ----- device authorization -----------------------------------------

    async def start_device_flow(self, *, user_key: str) -> DeviceCode:
        return await self._gateway.request_device_code(
            device_name=self._device_name, device_id=oauth_device_id(user_key)
        )

    async def revoke(self, access_token: str) -> bool:
        return await self._gateway.revoke_token(access_token)

    async def poll_device_flow(self, device_code: str) -> YandexToken:
        """One poll. Returns the token, or raises DeviceFlowPending/DeviceFlowError."""
        token = await self._gateway.poll_device_token(device_code)
        if token is None:
            raise DeviceFlowPending
        return token

    def token_expiry(self, token: YandexToken) -> datetime | None:
        if token.expires_in is None or token.expires_in <= 0:
            return None
        return self._clock() + timedelta(seconds=token.expires_in)

    # ----- playback -----------------------------------------------------

    async def fetch_playback(self, credentials: Credentials, *, subject_key: str) -> FetchResult:
        token = credentials.access_token
        if not token:
            raise ProviderError("provider_reauth_required", "no token", reauth_required=True)
        if credentials.expires_at is not None and credentials.expires_at <= self._clock():
            # yandex-music 3.2.2 cannot refresh tokens; the user re-approves instead.
            raise ProviderError("provider_reauth_required", "token expired", reauth_required=True)

        snapshot = await self._gateway.fetch_player_state(
            token, device_id=ynison_device_id(subject_key), device_title=self._device_title
        )
        if not snapshot.has_active_device or snapshot.playable is None:
            return FetchResult(ProviderPlayback(PlaybackStatus.IDLE, detail_code="nothing_playing"))

        status = PlaybackStatus.PAUSED if snapshot.paused else PlaybackStatus.PLAYING
        playable = snapshot.playable
        if playable.kind == "track":
            meta = await self._track_meta(token, playable.playable_id)
            track = self._track_info(playable, meta, snapshot.duration_ms)
            if track is None:
                return FetchResult(
                    ProviderPlayback(
                        status, content_type=ContentType.OTHER, detail_code="incomplete_metadata"
                    )
                )
            content = ContentType.TRACK
        elif playable.kind == "local_track" and playable.title:
            track = TrackInfo(
                title=playable.title,
                duration_ms=snapshot.duration_ms,
                provider_track_id=playable.playable_id,
            )
            content = ContentType.LOCAL_TRACK
        else:
            return FetchResult(
                ProviderPlayback(
                    status, content_type=ContentType.OTHER, detail_code="non_music_content"
                )
            )

        progress = snapshot.progress_ms
        if progress is not None and track.duration_ms is not None:
            progress = min(progress, track.duration_ms)
        return FetchResult(
            ProviderPlayback(status, content_type=content, track=track, progress_ms=progress)
        )

    def _track_info(
        self, playable: YnisonPlayable, meta: YandexTrackMeta | None, duration_ms: int | None
    ) -> TrackInfo | None:
        title = (meta.title if meta else None) or playable.title
        if not title:
            return None
        track_id = playable.playable_id.split(":", 1)[0]
        album_id = playable.album_id or (meta.album_id if meta else None)
        track_url = None
        if _NUMERIC_ID.fullmatch(track_id) and album_id and _NUMERIC_ID.fullmatch(album_id):
            track_url = safe_https_url(
                f"{self._web_base}/album/{album_id}/track/{track_id}", YANDEX_LINK_HOSTS
            )
        return TrackInfo(
            title=title,
            artist_names=meta.artist_names if meta else (),
            album=meta.album_title if meta else None,
            artwork_url=yandex_cover_url(meta.cover_uri if meta else None)
            or yandex_cover_url(playable.cover_url),
            track_url=track_url,
            duration_ms=duration_ms or (meta.duration_ms if meta else None),
            provider_track_id=track_id,
        )

    async def _track_meta(self, token: str, playable_id: str) -> YandexTrackMeta | None:
        track_id = playable_id.split(":", 1)[0]
        if not _NUMERIC_ID.fullmatch(track_id):
            return None
        now = self._monotonic()
        cached = self._meta_cache.get(track_id)
        if cached is not None and cached[0] > now:
            self._meta_cache.move_to_end(track_id)
            return cached[1]
        meta = await self._gateway.fetch_track(token, track_id)
        ttl = _META_TTL_SECONDS if meta is not None else _META_FAILURE_TTL_SECONDS
        self._meta_cache[track_id] = (now + ttl, meta)
        self._meta_cache.move_to_end(track_id)
        while len(self._meta_cache) > _META_MAX_ENTRIES:
            self._meta_cache.popitem(last=False)
        return meta
