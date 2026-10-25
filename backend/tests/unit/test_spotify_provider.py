"""Spotify adapter against mocked HTTP (respx). No real Spotify calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.providers.base import ContentType, Credentials, PlaybackStatus, ProviderError
from app.providers.spotify import (
    CURRENTLY_PLAYING_URL,
    TOKEN_URL,
    SpotifyProvider,
    code_challenge_s256,
    new_code_verifier,
    parse_currently_playing,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def track_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "is_playing": True,
        "progress_ms": 61_000,
        "timestamp": 1761400000000,
        "currently_playing_type": "track",
        "device": {"is_private_session": False, "name": "iPhone"},
        "item": {
            "type": "track",
            "id": "4uLU6hMCjMI75M1A2tKUQC",
            "name": "Song Title",
            "duration_ms": 200_000,
            "is_local": False,
            "artists": [{"name": "Artist One"}, {"name": "Artist Two"}, {"bogus": 1}],
            "album": {
                "name": "Album Name",
                "images": [
                    {"url": "https://i.scdn.co/image/640", "width": 640, "height": 640},
                    {"url": "https://i.scdn.co/image/300", "width": 300, "height": 300},
                    {"url": "https://i.scdn.co/image/64", "width": 64, "height": 64},
                ],
            },
            "external_urls": {"spotify": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"},
        },
    }
    body.update(overrides)
    return body


# ----- parsing ------------------------------------------------------------------------


def test_parse_playing_track() -> None:
    playback = parse_currently_playing(track_body())
    assert playback.status is PlaybackStatus.PLAYING
    assert playback.is_playing is True
    assert playback.content_type is ContentType.TRACK
    track = playback.track
    assert track is not None
    assert track.title == "Song Title"
    assert track.artist_names == ("Artist One", "Artist Two")
    assert track.album == "Album Name"
    assert track.artwork_url == "https://i.scdn.co/image/300"  # smallest >= 300px
    assert track.track_url == "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"
    assert track.duration_ms == 200_000
    assert playback.progress_ms == 61_000


def test_parse_paused_is_not_playing() -> None:
    playback = parse_currently_playing(track_body(is_playing=False))
    assert playback.status is PlaybackStatus.PAUSED
    assert playback.is_playing is False


def test_parse_private_session_reveals_nothing() -> None:
    playback = parse_currently_playing(track_body(device={"is_private_session": True}))
    assert playback.status is PlaybackStatus.PRIVATE
    assert playback.track is None
    assert playback.progress_ms is None


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("episode", ContentType.EPISODE), ("ad", ContentType.AD), ("unknown", ContentType.OTHER)],
)
def test_parse_non_track_content(kind: str, expected: ContentType) -> None:
    playback = parse_currently_playing(track_body(item=None, currently_playing_type=kind))
    assert playback.content_type is expected
    assert playback.track is None
    assert playback.detail_code == "non_music_content"


def test_parse_local_track_has_no_link_or_artwork() -> None:
    body = track_body()
    body["item"]["is_local"] = True
    playback = parse_currently_playing(body)
    assert playback.content_type is ContentType.LOCAL_TRACK
    assert playback.track is not None
    assert playback.track.track_url is None
    assert playback.track.artwork_url is None


def test_parse_rejects_foreign_hosts_and_clamps_progress() -> None:
    body = track_body(progress_ms=999_999)
    body["item"]["album"]["images"] = [{"url": "https://evil.example/x.png", "width": 640}]
    body["item"]["external_urls"] = {"spotify": "https://evil.example/track"}
    body["item"]["album"]["name"] = ""  # album takedown
    playback = parse_currently_playing(body)
    assert playback.track is not None
    assert playback.track.artwork_url is None
    assert playback.track.track_url is None
    assert playback.track.album is None
    assert playback.progress_ms == 200_000


def test_parse_missing_title_and_garbage() -> None:
    body = track_body()
    body["item"]["name"] = "  "
    assert parse_currently_playing(body).detail_code == "incomplete_metadata"
    with pytest.raises(ProviderError) as excinfo:
        parse_currently_playing(["not", "an", "object"])
    assert excinfo.value.code == "provider_bad_response"


def test_pkce_helpers() -> None:
    verifier = new_code_verifier()
    assert 43 <= len(verifier) <= 128
    # RFC 7636 appendix B test vector
    assert (
        code_challenge_s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


# ----- HTTP behaviour -------------------------------------------------------------------


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def provider(http: httpx.AsyncClient) -> SpotifyProvider:
    return SpotifyProvider(
        http,
        client_id="cid",
        redirect_uri="http://127.0.0.1:3000/api/v1/providers/spotify/callback",
        clock=lambda: NOW,
    )


def creds(expires_in: timedelta = timedelta(minutes=30)) -> Credentials:
    return Credentials(
        access_token="old-access", refresh_token="refresh-1", expires_at=NOW + expires_in
    )


def test_authorize_url_uses_pkce_and_minimal_scope(provider: SpotifyProvider) -> None:
    url = provider.authorize_url(state="st", code_challenge="ch")
    parts = urlsplit(url)
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://accounts.spotify.com/authorize"
    )
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert query == {
        "client_id": "cid",
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:3000/api/v1/providers/spotify/callback",
        "state": "st",
        "scope": "user-read-currently-playing",
        "code_challenge_method": "S256",
        "code_challenge": "ch",
    }


@respx.mock
async def test_204_means_idle(provider: SpotifyProvider) -> None:
    route = respx.get(CURRENTLY_PLAYING_URL).mock(return_value=httpx.Response(204))
    result = await provider.fetch_playback(creds(), subject_key="x")
    assert result.playback.status is PlaybackStatus.IDLE
    assert result.new_tokens is None
    assert route.calls.last.request.headers["Authorization"] == "Bearer old-access"


@respx.mock
async def test_200_track(provider: SpotifyProvider) -> None:
    respx.get(CURRENTLY_PLAYING_URL).mock(return_value=httpx.Response(200, json=track_body()))
    result = await provider.fetch_playback(creds(), subject_key="x")
    assert result.playback.track is not None
    assert result.playback.track.title == "Song Title"


@respx.mock
async def test_401_refreshes_once_and_retries(provider: SpotifyProvider) -> None:
    respx.get(CURRENTLY_PLAYING_URL).mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json=track_body())]
    )
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "new-access", "token_type": "Bearer", "expires_in": 3600},
        )
    )
    result = await provider.fetch_playback(creds(), subject_key="x")
    assert result.new_tokens is not None
    assert result.new_tokens.access_token == "new-access"
    # No new refresh token returned -> keep using the old one (per Spotify docs).
    assert result.new_tokens.refresh_token == "refresh-1"
    assert result.new_tokens.expires_at == NOW + timedelta(seconds=3600)
    form = parse_qs(token_route.calls.last.request.content.decode())
    assert form == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["refresh-1"],
        "client_id": ["cid"],
    }


@respx.mock
async def test_expired_token_refreshes_before_calling(provider: SpotifyProvider) -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "refresh-2",
            },
        )
    )
    playing = respx.get(CURRENTLY_PLAYING_URL).mock(return_value=httpx.Response(204))
    result = await provider.fetch_playback(creds(timedelta(seconds=30)), subject_key="x")
    assert playing.calls.last.request.headers["Authorization"] == "Bearer fresh"
    assert result.new_tokens is not None
    assert result.new_tokens.refresh_token == "refresh-2"


@respx.mock
async def test_invalid_grant_requires_reauth(provider: SpotifyProvider) -> None:
    respx.get(CURRENTLY_PLAYING_URL).mock(return_value=httpx.Response(401))
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "x"})
    )
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_playback(creds(), subject_key="x")
    assert excinfo.value.code == "provider_reauth_required"
    assert excinfo.value.reauth_required


@respx.mock
async def test_refreshed_token_rejected_means_reauth(provider: SpotifyProvider) -> None:
    respx.get(CURRENTLY_PLAYING_URL).mock(return_value=httpx.Response(401))
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new", "token_type": "Bearer"})
    )
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_playback(creds(), subject_key="x")
    assert excinfo.value.reauth_required


@respx.mock
async def test_invalid_client_is_a_configuration_problem(provider: SpotifyProvider) -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_client"}))
    with pytest.raises(ProviderError) as excinfo:
        await provider.refresh("refresh-1")
    assert excinfo.value.code == "provider_not_configured"
    assert not excinfo.value.reauth_required


async def test_missing_refresh_token_requires_reauth(provider: SpotifyProvider) -> None:
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_playback(Credentials(None, None, None), subject_key="x")
    assert excinfo.value.reauth_required


@respx.mock
@pytest.mark.parametrize(
    ("response", "code", "retry_after"),
    [
        (
            httpx.Response(403, json={"error": {"status": 403, "message": "x"}}),
            "provider_forbidden",
            600.0,
        ),
        (httpx.Response(429, headers={"Retry-After": "7"}), "provider_rate_limited", 7.0),
        (httpx.Response(429), "provider_rate_limited", 30.0),
        (
            httpx.Response(
                429,
                headers={"Retry-After": "10"},
                json={"error": {"status": 429, "message": "x", "reason": "QUOTA_EXCEEDED"}},
            ),
            "provider_quota_exceeded",
            300.0,
        ),
        (httpx.Response(503), "provider_unreachable", None),
        (httpx.Response(404), "provider_bad_response", None),
        (httpx.Response(200, content=b"not json"), "provider_bad_response", None),
    ],
)
async def test_error_mapping(
    provider: SpotifyProvider, response: httpx.Response, code: str, retry_after: float | None
) -> None:
    respx.get(CURRENTLY_PLAYING_URL).mock(return_value=response)
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_playback(creds(), subject_key="x")
    assert excinfo.value.code == code
    assert excinfo.value.retry_after_seconds == retry_after
    assert not excinfo.value.reauth_required


@respx.mock
async def test_timeouts_and_network_errors(provider: SpotifyProvider) -> None:
    respx.get(CURRENTLY_PLAYING_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_playback(creds(), subject_key="x")
    assert excinfo.value.code == "provider_unreachable"
    respx.get(CURRENTLY_PLAYING_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_playback(creds(), subject_key="x")
    assert excinfo.value.code == "provider_unreachable"


@respx.mock
async def test_exchange_code_sends_pkce_verifier_without_secret(provider: SpotifyProvider) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "a",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "r",
                "scope": "user-read-currently-playing",
            },
        )
    )
    tokens = await provider.exchange_code("the-code", "the-verifier")
    request = route.calls.last.request
    assert "Authorization" not in request.headers  # public PKCE client: no secret
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["the-code"],
        "redirect_uri": ["http://127.0.0.1:3000/api/v1/providers/spotify/callback"],
        "client_id": ["cid"],
        "code_verifier": ["the-verifier"],
    }
    assert tokens.refresh_token == "r"
    assert tokens.scopes == "user-read-currently-playing"


@respx.mock
async def test_token_response_validation(provider: SpotifyProvider) -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"token_type": "Bearer"}))
    with pytest.raises(ProviderError):
        await provider.exchange_code("c", "v")
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "token_type": "MAC"})
    )
    with pytest.raises(ProviderError):
        await provider.exchange_code("c", "v")
