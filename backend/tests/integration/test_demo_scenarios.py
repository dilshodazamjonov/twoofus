"""Development-only demo scenarios run through the real now-playing pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from app.context import AppContext
from tests.conftest import ApiClient, FakeClock, enable_sharing


async def me_playback(client: ApiClient) -> dict[str, Any]:
    response = await client.get("/api/v1/room/now-playing")
    assert response.status_code == 200, response.text
    playback: dict[str, Any] = response.json()["me"]["playback"]
    return playback


async def pin(client: ApiClient, scenario: str) -> None:
    response = await client.put("/api/v1/providers/demo/scenario", json={"scenario": scenario})
    assert response.status_code == 200, response.text
    assert response.json()["scenario"] == scenario


async def test_requires_a_demo_connection(owner_client: ApiClient) -> None:
    response = await owner_client.put("/api/v1/providers/demo/scenario", json={"scenario": "idle"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_demo"
    await owner_client.post("/api/v1/providers/demo/connect")
    current = await owner_client.get("/api/v1/providers/demo/scenario")
    assert current.json()["scenario"] == "live"
    assert "rate_limited" in current.json()["available"]
    bad = await owner_client.put("/api/v1/providers/demo/scenario", json={"scenario": "nope"})
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("scenario", "status", "detail", "has_track"),
    [
        ("playing", "playing", None, True),
        ("paused", "paused", None, True),
        ("idle", "idle", "nothing_playing", False),
        ("non_music", "playing", "non_music_content", False),
        ("private_session", "private", "provider_private_session", False),
    ],
)
async def test_playback_scenarios(
    owner_client: ApiClient, scenario: str, status: str, detail: str | None, has_track: bool
) -> None:
    await owner_client.post("/api/v1/providers/demo/connect")
    await me_playback(owner_client)  # fill the cache first: the switch must bypass it
    await pin(owner_client, scenario)
    playback = await me_playback(owner_client)
    assert playback["status"] == status
    assert playback["detail_code"] == detail
    assert (playback["track_title"] is not None) is has_track
    assert playback["is_demo"] is True
    assert playback["is_stale"] is False


async def test_rate_limit_serves_the_last_song_as_stale_then_recovers(
    owner_client: ApiClient, clock: FakeClock, ctx: AppContext
) -> None:
    await owner_client.post("/api/v1/providers/demo/connect")
    await pin(owner_client, "playing")
    good = await me_playback(owner_client)
    await pin(owner_client, "rate_limited")
    stale = await me_playback(owner_client)
    assert stale["is_stale"] is True
    assert stale["detail_code"] == "provider_rate_limited"
    assert stale["track_title"] == good["track_title"]
    assert stale["progress_ms"] is None  # never extrapolated from stale data
    calls = ctx.now_playing.upstream_calls
    clock.advance(seconds=10)
    await me_playback(owner_client)
    assert ctx.now_playing.upstream_calls == calls  # Retry-After is honoured

    clock.advance(minutes=6)  # older than the 5-minute stale limit
    await pin(owner_client, "unreachable")
    gone = await me_playback(owner_client)
    assert gone["status"] == "unavailable"
    assert gone["track_title"] is None

    await pin(owner_client, "live")
    assert (await me_playback(owner_client))["status"] in {"playing", "paused", "idle"}


async def test_reauth_scenario_marks_the_connection(owner_client: ApiClient) -> None:
    await owner_client.post("/api/v1/providers/demo/connect")
    await pin(owner_client, "reauth_required")
    playback = await me_playback(owner_client)
    assert playback["status"] == "error"
    assert playback["detail_code"] == "provider_reauth_required"
    connection = (await owner_client.get("/api/v1/providers")).json()["connection"]
    assert connection["status"] == "reauth_required"
    # Reconnecting starts fresh on the live timeline.
    await owner_client.post("/api/v1/providers/demo/connect")
    assert (await owner_client.get("/api/v1/providers/demo/scenario")).json()["scenario"] == "live"
    assert (await me_playback(owner_client))["status"] in {"playing", "paused", "idle"}


async def test_partner_sees_scenarios_only_while_sharing(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    await partner_client.post("/api/v1/providers/demo/connect")
    await pin(partner_client, "playing")
    partner = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
    assert partner["status"] == "private"
    await enable_sharing(partner_client)
    partner = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
    assert partner["status"] == "playing"
    # Each member can only pin their own connection.
    await owner_client.post("/api/v1/providers/demo/connect")
    await pin(owner_client, "idle")
    partner = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
    assert partner["status"] == "playing"


@pytest.mark.parametrize("settings_overrides", [{"demo_mode": False}])
async def test_hidden_when_demo_mode_is_off(owner_client: ApiClient) -> None:
    config = (await owner_client.get("/api/v1/config")).json()
    assert config["demo_mode"] is False
    assert config["demo_controls"] is False
    assert (await owner_client.get("/api/v1/providers/demo/scenario")).status_code == 404
    response = await owner_client.put("/api/v1/providers/demo/scenario", json={"scenario": "idle"})
    assert response.status_code == 404


async def test_config_advertises_demo_controls_in_development(owner_client: ApiClient) -> None:
    config = (await owner_client.get("/api/v1/config")).json()
    assert config["demo_mode"] is True
    assert config["demo_controls"] is True
