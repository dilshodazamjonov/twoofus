"""The real provider adapters, over real sockets, against tests/fakes/providers.py.

Nothing here is mocked inside the backend: Spotify goes through httpx, Yandex
ID OAuth through httpx, Ynison through the yandex-music library's WebSocket
client and track metadata through its HTTP client. Only the far end is fake.
"""

from __future__ import annotations

import html
import re
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn

from tests.conftest import (
    APP_ORIGIN,
    SPOTIFY_REDIRECT,
    ApiClient,
    FakeClock,
    enable_sharing,
)
from tests.fakes.providers import FakeState
from tests.fakes.providers import create_app as create_fake

CLIENT_ID = "fake-client-id-for-tests"


@pytest.fixture(scope="module")
def fake() -> Iterator[tuple[str, FakeState]]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    state = FakeState(spotify_client_id=CLIENT_ID, spotify_redirect=SPOTIFY_REDIRECT)
    server = uvicorn.Server(
        uvicorn.Config(
            create_fake(state), host="127.0.0.1", port=port, log_level="warning", lifespan="off"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "fake provider server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", state
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def fresh_fake(fake: tuple[str, FakeState]) -> None:
    _, state = fake
    state.spotify_scenario = "playing"
    state.yandex_scenario = "playing"
    state.log.clear()


@pytest.fixture
def yandex_gateway() -> None:  # the real gateway, not the in-process fake
    return None


@pytest.fixture
def settings_overrides(fake: tuple[str, FakeState]) -> dict[str, Any]:
    return {
        "provider_upstream_override": fake[0],
        "spotify_client_id": CLIENT_ID,
        "now_playing_ttl_seconds": 1,
        "provider_timeout_seconds": 2,
    }


def events(state: FakeState, service: str) -> list[str]:
    return [entry["event"] for entry in state.log if entry["service"] == service]


async def me_playback(client: ApiClient, clock: FakeClock, seconds: float = 2) -> dict[str, Any]:
    clock.advance(seconds=seconds)  # past the cache TTL / any backoff
    body: dict[str, Any] = (await client.get("/api/v1/room/now-playing")).json()
    return dict(body["me"]["playback"])


async def connect_spotify(client: ApiClient, base: str) -> httpx.Response:
    url = (await client.post("/api/v1/providers/spotify/authorize")).json()["authorization_url"]
    assert url.startswith("https://accounts.spotify.com/authorize?")
    # The browser would now be on Spotify's consent page; the fake serves it.
    async with httpx.AsyncClient() as browser:
        page = await browser.get(f"{base}/spotify/accounts/authorize?{urlsplit(url).query}")
    assert page.status_code == 200, page.text
    match = re.search(r"id=agree href='([^']+)'", page.text)
    assert match is not None
    callback = html.unescape(match.group(1))
    assert callback.startswith(SPOTIFY_REDIRECT + "?")
    return await client.get(callback.removeprefix(APP_ORIGIN))


async def test_spotify_login_playback_states_refresh_and_revocation(
    owner_client: ApiClient, fake: tuple[str, FakeState], clock: FakeClock
) -> None:
    base, state = fake
    landed = await connect_spotify(owner_client, base)
    assert landed.status_code == 303
    assert landed.headers["location"] == "/connect?connect=spotify&result=connected"
    assert "pkce_verified" in events(state, "spotify")
    assert "client_secret_sent" not in events(state, "spotify")
    assert "unexpected_query" not in events(state, "spotify")

    playing = await me_playback(owner_client, clock)
    assert playing["source"] == "spotify"
    assert playing["status"] == "playing"
    assert playing["track_title"] == "Fake Spotify Song"
    assert playing["artist_names"] == ["Test Artist", "Second Artist"]
    assert playing["artwork_url"] == "https://i.scdn.co/image/fake-cover-300"
    assert playing["track_url"] == "https://open.spotify.com/track/4fakeTrackId0000000000"
    assert playing["progress_ms"] == 42_000
    assert playing["is_stale"] is False

    expectations: list[tuple[str, dict[str, Any]]] = [
        ("paused", {"status": "paused", "is_playing": False}),
        ("idle", {"status": "idle", "detail_code": "nothing_playing", "track_title": None}),
        ("private", {"status": "private", "detail_code": "provider_private_session"}),
        ("episode", {"content_type": "episode", "track_title": None}),
        ("local", {"content_type": "local_track", "artwork_url": None, "track_url": None}),
        ("no_artwork", {"status": "playing", "artwork_url": None}),
        ("unknown_position", {"status": "playing", "progress_ms": None}),
    ]
    for scenario, expected in expectations:
        state.spotify_scenario = scenario
        view = await me_playback(owner_client, clock)
        assert {key: view[key] for key in expected} == expected, scenario
        if scenario == "private":
            assert view["track_title"] is None
            assert view["artwork_url"] is None

    # Failures: the last good state is served as stale, never as live.
    state.spotify_scenario = "playing"
    await me_playback(owner_client, clock)
    failures = [
        ("rate_limited", "provider_rate_limited", 3),
        ("server_error", "provider_unreachable", 16),
        ("bad_json", "provider_bad_response", 31),
        ("timeout", "provider_unreachable", 61),
    ]
    for scenario, detail, wait_after in failures:
        state.spotify_scenario = scenario
        view = await me_playback(owner_client, clock)
        assert view["is_stale"] is True, scenario
        assert view["detail_code"] == detail
        assert view["progress_ms"] is None  # never extrapolated from stale data
        state.spotify_scenario = "playing"
        clock.advance(seconds=wait_after)  # let the backoff run out
        recovered = await me_playback(owner_client, clock)
        assert (recovered["status"], recovered["is_stale"]) == ("playing", False), scenario

    # An expired access token is refreshed transparently.
    async with httpx.AsyncClient() as control:
        await control.post(f"{base}/_control/expire-access")
    refreshed = await me_playback(owner_client, clock)
    assert refreshed["status"] == "playing"
    assert "refreshed" in events(state, "spotify")

    # A revoked grant needs the person to reconnect; nothing invented meanwhile.
    state.spotify_scenario = "revoked"
    async with httpx.AsyncClient() as control:
        await control.post(f"{base}/_control/expire-access")
    revoked = await me_playback(owner_client, clock)
    assert (revoked["status"], revoked["detail_code"]) == ("error", "provider_reauth_required")
    assert revoked["track_title"] is None
    providers = (await owner_client.get("/api/v1/providers")).json()
    assert providers["connection"]["status"] == "reauth_required"

    disconnected = (await owner_client.delete("/api/v1/providers/connection")).json()
    assert disconnected == {"provider": "spotify", "provider_revocation": "not_supported"}


async def test_spotify_rejects_a_wrong_redirect_and_denial(
    owner_client: ApiClient, fake: tuple[str, FakeState]
) -> None:
    base, _ = fake
    url = (await owner_client.post("/api/v1/providers/spotify/authorize")).json()[
        "authorization_url"
    ]
    query = urlsplit(url).query.replace("callback", "callbackX")
    async with httpx.AsyncClient() as browser:
        page = await browser.get(f"{base}/spotify/accounts/authorize?{query}")
    assert page.status_code == 400
    assert "Invalid redirect URI" in page.text

    async with httpx.AsyncClient() as browser:
        page = await browser.get(f"{base}/spotify/accounts/authorize?{urlsplit(url).query}")
    match = re.search(r"id=cancel href='([^']+)'", page.text)
    assert match is not None
    denied = await owner_client.get(html.unescape(match.group(1)).removeprefix(APP_ORIGIN))
    assert denied.headers["location"] == "/connect?connect=spotify&result=access_denied"


async def test_yandex_device_flow_ynison_states_and_revocation(
    owner_client: ApiClient,
    partner_client: ApiClient,
    fake: tuple[str, FakeState],
    clock: FakeClock,
) -> None:
    base, state = fake
    started = await partner_client.post("/api/v1/providers/yandex/device-authorization")
    assert started.status_code == 201, started.text
    flow = started.json()
    assert re.fullmatch(r"\d{7}", flow["user_code"])
    assert flow["verification_url"] == "https://ya.ru/device"

    clock.advance(seconds=3)
    pending = await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    assert pending.json()["status"] == "pending"
    async with httpx.AsyncClient() as control:  # she taps "Allow" on Yandex's page
        assert (await control.post(f"{base}/_control/yandex/approve")).json()["updated"] == 1
    clock.advance(seconds=3)
    done = await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    assert done.json()["status"] == "completed"
    assert events(state, "yandex")[:3] == ["device_code", "user_approved", "token_issued"]

    # Not shared yet: the owner sees nothing, and Yandex is not even asked.
    hidden = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
    assert (hidden["status"], hidden["source"]) == ("private", None)
    assert "handshake" not in events(state, "ynison")

    await enable_sharing(partner_client)
    clock.advance(seconds=2)
    shown = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
    assert shown["source"] == "yandex"
    assert shown["experimental"] is True
    assert shown["status"] == "playing"
    assert shown["track_title"] == "Fake Yandex Song"
    assert shown["artist_names"] == ["Fixture Singer"]
    assert shown["album"] == "Fake Album"
    assert shown["artwork_url"] == "https://avatars.yandex.net/get-music-content/fake/cover/400x400"
    assert shown["track_url"] == "https://music.yandex.ru/album/1193829/track/10994777"
    assert shown["progress_ms"] is not None
    assert shown["progress_ms"] >= 61_000
    handshakes = [e for e in state.log if e["event"] == "handshake"]
    assert handshakes
    assert all(h["read_only"] for h in handshakes)

    expectations: list[tuple[str, dict[str, Any]]] = [
        ("paused", {"status": "paused"}),
        ("no_device", {"status": "idle", "detail_code": "nothing_playing"}),
        ("offline_device", {"status": "idle"}),
        ("no_track", {"status": "idle"}),
        ("playing", {"status": "playing", "is_stale": False}),
        ("go_away", {"is_stale": True, "detail_code": "provider_rate_limited"}),
        ("playing", {"status": "playing", "is_stale": False}),
        ("malformed", {"is_stale": True, "detail_code": "provider_unreachable"}),
        ("playing", {"status": "playing", "is_stale": False}),
        ("timeout", {"is_stale": True, "detail_code": "provider_unreachable"}),
        ("playing", {"status": "playing", "is_stale": False}),
        ("unauthorized", {"status": "error", "detail_code": "provider_reauth_required"}),
    ]
    for scenario, expected in expectations:
        state.yandex_scenario = scenario
        clock.advance(seconds=61)  # past TTL and any backoff from the previous step
        view = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
        assert {key: view[key] for key in expected} == expected, scenario
    assert "unexpected_message" not in events(state, "ynison")  # read-only: no commands

    async with httpx.AsyncClient() as control:
        tokens_before = (await control.get(f"{base}/_control/state")).json()
    gone = (await partner_client.delete("/api/v1/providers/connection")).json()
    assert gone == {"provider": "yandex", "provider_revocation": "revoked"}
    async with httpx.AsyncClient() as control:
        after = (await control.get(f"{base}/_control/state")).json()
    assert after["yandex_valid_tokens"] == tokens_before["yandex_valid_tokens"] - 1
    assert "token_revoked" in events(state, "yandex")
