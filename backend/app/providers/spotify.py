"""Spotify Web API adapter (official API).

* Authorization Code with PKCE, done server-side: the code verifier never
  reaches the browser and no client secret is needed.
  https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
* Scopes: ``user-read-currently-playing`` and ``user-read-recently-played``.
* Playback: ``GET /v1/me/player/currently-playing``
  https://developer.spotify.com/documentation/web-api/reference/get-the-users-currently-playing-track
* Recent songs: ``GET /v1/me/player/recently-played``
  https://developer.spotify.com/documentation/web-api/reference/get-recently-played
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import SPOTIFY_SCOPES
from app.models.enums import ProviderName
from app.providers.base import (
    ContentType,
    Credentials,
    FetchResult,
    PlaybackStatus,
    ProviderError,
    ProviderPlayback,
    RecentResult,
    RecentTrack,
    TokenSet,
    TrackInfo,
)
from app.providers.urls import SPOTIFY_ARTWORK_HOSTS, SPOTIFY_LINK_HOSTS, safe_https_url

# Fixed upstream hosts. The browser is sent to AUTHORIZE_URL; the server only
# ever calls the token endpoint and the API host.
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
ACCOUNTS_BASE = "https://accounts.spotify.com"
API_BASE = "https://api.spotify.com"
TOKEN_PATH = "/api/token"  # noqa: S105 - URL path, not a secret
CURRENTLY_PLAYING_PATH = "/v1/me/player/currently-playing"
RECENTLY_PLAYED_PATH = "/v1/me/player/recently-played"
TOKEN_URL = ACCOUNTS_BASE + TOKEN_PATH
CURRENTLY_PLAYING_URL = API_BASE + CURRENTLY_PLAYING_PATH
RECENTLY_PLAYED_URL = API_BASE + RECENTLY_PLAYED_PATH
# Grants from before this scope was requested keep working for playback.
RECENT_SCOPE = "user-read-recently-played"
# One page holds repeats; ask for more than we show.
_RECENT_PAGE = 20
_TRACK_ID = re.compile(r"[0-9A-Za-z]{1,64}")

# Refresh a little before expiry so a request never races the deadline.
_EXPIRY_SKEW = timedelta(seconds=60)
_DEFAULT_RETRY_AFTER = 30.0
_MAX_RETRY_AFTER = 3600.0
_FORBIDDEN_BACKOFF = 600.0
_QUOTA_MIN_BACKOFF = 300.0


def new_code_verifier() -> str:
    """43-128 chars from the unreserved set (RFC 7636); 64 random bytes -> 86 chars."""
    return secrets.token_urlsafe(64)


def code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_RETRY_AFTER
    return min(max(value, 1.0), _MAX_RETRY_AFTER)


def _error_reason(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("reason"), str):
            return str(error["reason"])
        if isinstance(error, str):  # OAuth errors: {"error": "invalid_grant", ...}
            return error
    return None


def _pick_artwork(images: object) -> str | None:
    """Prefer the smallest image that is still >= 300px wide (cards are small)."""
    if not isinstance(images, list):
        return None
    candidates: list[tuple[int, str]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        url = safe_https_url(image.get("url"), SPOTIFY_ARTWORK_HOSTS)
        if url is None:
            continue
        width = image.get("width")
        candidates.append((width if isinstance(width, int) else 0, url))
    if not candidates:
        return None
    big_enough = [c for c in candidates if c[0] >= 300]
    return min(big_enough)[1] if big_enough else max(candidates)[1]


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _artist_names(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(a["name"])
        for a in item.get("artists") or []
        if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"]
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def parse_recently_played(data: object, limit: int) -> tuple[RecentTrack, ...]:
    """Distinct songs from a recently-played page, newest first."""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ProviderError("provider_bad_response", "recently-played body is not a page")
    tracks: list[RecentTrack] = []
    seen: set[str] = set()
    for entry in items:
        item = entry.get("track") if isinstance(entry, dict) else None
        if (
            not isinstance(item, dict)
            or item.get("type") != "track"
            or item.get("is_local") is True
        ):
            continue
        track_id, title = item.get("id"), item.get("name")
        if not isinstance(track_id, str) or not _TRACK_ID.fullmatch(track_id) or track_id in seen:
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        seen.add(track_id)
        raw_album = item.get("album")
        album: dict[str, Any] = raw_album if isinstance(raw_album, dict) else {}
        raw_external = item.get("external_urls")
        external: dict[str, Any] = raw_external if isinstance(raw_external, dict) else {}
        tracks.append(
            RecentTrack(
                key=track_id,
                title=title,
                artist_names=_artist_names(item),
                artwork_url=_pick_artwork(album.get("images")),
                track_url=safe_https_url(external.get("spotify"), SPOTIFY_LINK_HOSTS),
                played_at=_timestamp(entry.get("played_at")),
            )
        )
        if len(tracks) == limit:
            break
    return tuple(tracks)


def parse_currently_playing(data: object) -> ProviderPlayback:
    """Translate a 200 response body into a provider-neutral playback state."""
    if not isinstance(data, dict):
        raise ProviderError("provider_bad_response", "currently-playing body is not an object")

    device = data.get("device")
    if isinstance(device, dict) and device.get("is_private_session") is True:
        return ProviderPlayback(PlaybackStatus.PRIVATE, detail_code="provider_private_session")

    status = PlaybackStatus.PLAYING if data.get("is_playing") is True else PlaybackStatus.PAUSED
    item = data.get("item")
    playing_type = data.get("currently_playing_type")

    if not isinstance(item, dict) or item.get("type") != "track":
        # Episodes (we do not request additional_types), ads, unknown types:
        # report that *something* is playing, without details.
        kind = item.get("type") if isinstance(item, dict) else playing_type
        content = {"episode": ContentType.EPISODE, "ad": ContentType.AD}.get(
            str(kind), ContentType.OTHER
        )
        return ProviderPlayback(status, content_type=content, detail_code="non_music_content")

    title = item.get("name")
    if not isinstance(title, str) or not title.strip():
        return ProviderPlayback(
            status, content_type=ContentType.OTHER, detail_code="incomplete_metadata"
        )

    artists = _artist_names(item)
    raw_album = item.get("album")
    album: dict[str, Any] = raw_album if isinstance(raw_album, dict) else {}
    album_name = album.get("name") if isinstance(album.get("name"), str) else None
    is_local = item.get("is_local") is True
    raw_external = item.get("external_urls")
    external: dict[str, Any] = raw_external if isinstance(raw_external, dict) else {}

    track = TrackInfo(
        title=title,
        artist_names=artists,
        album=album_name or None,  # empty string after an album takedown
        artwork_url=None if is_local else _pick_artwork(album.get("images")),
        track_url=None if is_local else safe_https_url(external.get("spotify"), SPOTIFY_LINK_HOSTS),
        duration_ms=_non_negative_int(item.get("duration_ms")) or None,
        provider_track_id=item.get("id") if isinstance(item.get("id"), str) else None,
    )
    progress = _non_negative_int(data.get("progress_ms"))
    if progress is not None and track.duration_ms is not None:
        progress = min(progress, track.duration_ms)
    return ProviderPlayback(
        status,
        content_type=ContentType.LOCAL_TRACK if is_local else ContentType.TRACK,
        track=track,
        progress_ms=progress,
    )


class _AccessTokenRejected(Exception):
    pass


class SpotifyProvider:
    name = ProviderName.SPOTIFY
    experimental = False

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        client_id: str,
        redirect_uri: str,
        clock: Callable[[], datetime],
        upstream_override: str | None = None,
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._clock = clock
        # Test fakes only (validated loopback URL, refused in production).
        accounts = f"{upstream_override}/spotify/accounts" if upstream_override else ACCOUNTS_BASE
        api = f"{upstream_override}/spotify/api" if upstream_override else API_BASE
        self._token_url = accounts + TOKEN_PATH
        self._currently_playing_url = api + CURRENTLY_PLAYING_PATH
        self._recently_played_url = api + RECENTLY_PLAYED_PATH

    # ----- authorization -------------------------------------------------

    def authorize_url(self, *, state: str, code_challenge: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "response_type": "code",
                "redirect_uri": self._redirect_uri,
                "state": state,
                "scope": " ".join(SPOTIFY_SCOPES),
                "code_challenge_method": "S256",
                "code_challenge": code_challenge,
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str, code_verifier: str) -> TokenSet:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._redirect_uri,
                "client_id": self._client_id,
                "code_verifier": code_verifier,
            },
            previous_refresh_token=None,
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        return await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
            },
            previous_refresh_token=refresh_token,
        )

    async def _token_request(
        self, form: dict[str, str], *, previous_refresh_token: str | None
    ) -> TokenSet:
        try:
            response = await self._http.post(
                self._token_url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("provider_unreachable", "token request timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderError("provider_unreachable", "token request failed") from exc

        if response.status_code == 200:
            return self._parse_token_response(response, previous_refresh_token)
        reason = _error_reason(response)
        if response.status_code in (400, 401) and reason == "invalid_grant":
            # Code/refresh token expired or revoked (refresh tokens live 6
            # months). The user has to authorise again.
            raise ProviderError("provider_reauth_required", reason, reauth_required=True)
        if response.status_code in (400, 401) and reason in {
            "invalid_client",
            "unauthorized_client",
        }:
            # Wrong client id / app settings: re-authorising would not help.
            raise ProviderError("provider_not_configured", reason)
        if response.status_code == 429:
            raise ProviderError(
                "provider_rate_limited", retry_after_seconds=_retry_after_seconds(response)
            )
        if response.status_code >= 500:
            raise ProviderError("provider_unreachable", f"token endpoint {response.status_code}")
        raise ProviderError("provider_bad_response", f"token endpoint {response.status_code}")

    def _parse_token_response(
        self, response: httpx.Response, previous_refresh_token: str | None
    ) -> TokenSet:
        try:
            body: Any = response.json()
        except ValueError as exc:
            raise ProviderError("provider_bad_response", "token body is not JSON") from exc
        access = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(access, str) or not access:
            raise ProviderError("provider_bad_response", "token response without access_token")
        if str(body.get("token_type", "Bearer")).lower() != "bearer":
            raise ProviderError("provider_bad_response", "unexpected token_type")
        expires_in = body.get("expires_in")
        expires_at = (
            self._clock() + timedelta(seconds=int(expires_in))
            if isinstance(expires_in, int) and expires_in > 0
            else None
        )
        refresh = body.get("refresh_token")
        scope = body.get("scope")
        return TokenSet(
            access_token=access,
            # "When a refresh token is not returned, continue using the existing token."
            refresh_token=refresh
            if isinstance(refresh, str) and refresh
            else previous_refresh_token,
            expires_at=expires_at,
            scopes=scope if isinstance(scope, str) else None,
        )

    # ----- playback -----------------------------------------------------

    async def fetch_playback(self, credentials: Credentials, *, subject_key: str) -> FetchResult:
        del subject_key
        playback, new_tokens = await self._with_access_token(credentials, self._currently_playing)
        return FetchResult(playback=playback, new_tokens=new_tokens)

    async def fetch_recent(
        self, credentials: Credentials, *, subject_key: str, limit: int
    ) -> RecentResult:
        del subject_key
        if credentials.scopes is not None and RECENT_SCOPE not in credentials.scopes.split():
            raise ProviderError("recent_not_permitted", "granted before recent songs were asked")

        async def call(access_token: str) -> tuple[RecentTrack, ...]:
            return await self._recently_played(access_token, limit)

        tracks, new_tokens = await self._with_access_token(credentials, call)
        return RecentResult(tracks=tracks, new_tokens=new_tokens)

    async def _with_access_token[T](
        self, credentials: Credentials, call: Callable[[str], Awaitable[T]]
    ) -> tuple[T, TokenSet | None]:
        """Run ``call`` with a valid access token, refreshing it at most once."""
        new_tokens: TokenSet | None = None
        access = credentials.access_token
        expires_at = credentials.expires_at
        if access is None or (
            expires_at is not None and expires_at - _EXPIRY_SKEW <= self._clock()
        ):
            new_tokens = await self._refresh_or_reauth(credentials.refresh_token)
            access = new_tokens.access_token

        try:
            return await call(access), new_tokens
        except _AccessTokenRejected:
            if new_tokens is not None:
                # A token we just refreshed was rejected: the grant is gone.
                raise ProviderError(
                    "provider_reauth_required", "fresh token rejected", reauth_required=True
                ) from None
            new_tokens = await self._refresh_or_reauth(credentials.refresh_token)
            try:
                return await call(new_tokens.access_token), new_tokens
            except _AccessTokenRejected:
                raise ProviderError(
                    "provider_reauth_required", "refreshed token rejected", reauth_required=True
                ) from None

    async def _refresh_or_reauth(self, refresh_token: str | None) -> TokenSet:
        if not refresh_token:
            raise ProviderError(
                "provider_reauth_required", "no refresh token", reauth_required=True
            )
        return await self.refresh(refresh_token)

    async def _currently_playing(self, access_token: str) -> ProviderPlayback:
        try:
            response = await self._http.get(
                self._currently_playing_url, headers={"Authorization": f"Bearer {access_token}"}
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("provider_unreachable", "currently-playing timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderError("provider_unreachable", "currently-playing failed") from exc

        status = response.status_code
        if status == 204 or (status == 200 and not response.content.strip()):
            # 204 No Content: nothing is playing / no active device.
            return ProviderPlayback(PlaybackStatus.IDLE, detail_code="nothing_playing")
        if status == 200:
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderError("provider_bad_response", "body is not JSON") from exc
            return parse_currently_playing(body)
        if status == 401:
            raise _AccessTokenRejected
        if status == 403:
            # Development-mode apps answer 403 for users missing from the app's
            # allowlist (or when the app owner lacks Premium). Re-auth won't help.
            raise ProviderError(
                "provider_forbidden",
                "Spotify refused access (allowlist / Premium / app settings)",
                retry_after_seconds=_FORBIDDEN_BACKOFF,
            )
        if status == 429:
            retry_after = _retry_after_seconds(response)
            if _error_reason(response) == "QUOTA_EXCEEDED":
                raise ProviderError(
                    "provider_quota_exceeded",
                    retry_after_seconds=max(retry_after, _QUOTA_MIN_BACKOFF),
                )
            raise ProviderError("provider_rate_limited", retry_after_seconds=retry_after)
        if status >= 500:
            raise ProviderError("provider_unreachable", f"Spotify returned {status}")
        raise ProviderError("provider_bad_response", f"Spotify returned {status}")

    async def _recently_played(self, access_token: str, limit: int) -> tuple[RecentTrack, ...]:
        try:
            response = await self._http.get(
                self._recently_played_url,
                params={"limit": _RECENT_PAGE},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("provider_unreachable", "recently-played timed out") from exc
        except httpx.TransportError as exc:
            raise ProviderError("provider_unreachable", "recently-played failed") from exc

        status = response.status_code
        if status == 200:
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderError("provider_bad_response", "body is not JSON") from exc
            return parse_recently_played(body, limit)
        if status == 401:
            raise _AccessTokenRejected
        if status == 403:
            # The grant lacks the history scope (or the app may not read it).
            raise ProviderError("recent_not_permitted", "Spotify refused recent songs")
        if status == 429:
            raise ProviderError(
                "provider_rate_limited", retry_after_seconds=_retry_after_seconds(response)
            )
        if status >= 500:
            raise ProviderError("provider_unreachable", f"Spotify returned {status}")
        raise ProviderError("provider_bad_response", f"Spotify returned {status}")
