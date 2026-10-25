"""The two-person view: consent filtering, caching, single flight, backoff."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.context import AppContext
from app.models import ConnectionStatus, ProviderConnection
from app.providers.base import (
    ContentType,
    Credentials,
    FetchResult,
    PlaybackStatus,
    ProviderError,
    ProviderPlayback,
    TokenSet,
    TrackInfo,
)
from app.services.members import ConnectionRef
from tests.conftest import ApiClient, FakeClock, enable_sharing


async def now_playing(client: ApiClient) -> dict[str, Any]:
    response = await client.get("/api/v1/room/now-playing")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_alone_and_not_connected(owner_client: ApiClient) -> None:
    body = await now_playing(owner_client)
    assert body["partner"] is None
    assert body["partner_joined"] is False
    assert body["poll_after_seconds"] == 20
    me = body["me"]
    assert me["is_me"] is True
    assert me["display_name"] == "Khaled"
    assert me["playback"]["status"] == "not_connected"
    assert me["playback"]["track_title"] is None
    assert me["playback"]["artist_names"] == []


async def test_consent_filter_runs_before_any_provider_call(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext
) -> None:
    assert (await partner_client.post("/api/v1/providers/demo/connect")).status_code == 200
    assert (await owner_client.post("/api/v1/providers/demo/connect")).status_code == 200

    body = await now_playing(owner_client)
    partner = body["partner"]["playback"]
    assert body["partner_joined"] is True
    assert partner["status"] == "private"
    assert partner["detail_code"] == "sharing_off"
    assert partner["source"] is None  # not even the service is revealed
    assert partner["track_title"] is None
    assert partner["artwork_url"] is None
    assert ctx.now_playing.upstream_calls == 1  # only the owner's own connection

    # The owner always sees their own playback, even while not sharing.
    me = body["me"]["playback"]
    assert me["source"] == "demo"
    assert me["is_demo"] is True
    assert me["status"] != "private"

    # Partner opts in -> the owner sees her (demo) song.
    await enable_sharing(partner_client)
    partner_view = (await now_playing(owner_client))["partner"]["playback"]
    assert partner_view["source"] == "demo"
    assert partner_view["is_demo"] is True
    assert partner_view["status"] in {"playing", "paused", "idle"}

    # Opt-out takes effect immediately, even inside the cache TTL.
    response = await partner_client.put("/api/v1/me/sharing", json={"share_now_playing": False})
    assert response.status_code == 200
    assert response.json()["share_now_playing"] is False
    hidden = (await now_playing(owner_client))["partner"]["playback"]
    assert hidden["status"] == "private"
    assert hidden["track_title"] is None


async def test_sharing_requires_acknowledging_the_notice(owner_client: ApiClient) -> None:
    refused = await owner_client.put("/api/v1/me/sharing", json={"share_now_playing": True})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "sharing_notice_not_acknowledged"
    stale = await owner_client.put(
        "/api/v1/me/sharing",
        json={"share_now_playing": True, "acknowledged_notice_version": "2020-01-01"},
    )
    assert stale.status_code == 409
    await enable_sharing(owner_client)
    sharing = (await owner_client.get("/api/v1/me/sharing")).json()
    assert sharing["share_now_playing"] is True
    assert sharing["notice_version_acknowledged"] == sharing["current_notice_version"]
    assert sharing["acknowledged_at"] is not None


async def test_cache_ttl_shared_between_both_members(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext, clock: FakeClock
) -> None:
    await partner_client.post("/api/v1/providers/demo/connect")
    await enable_sharing(partner_client)
    for _ in range(3):
        await now_playing(owner_client)
        await now_playing(partner_client)
    assert ctx.now_playing.upstream_calls == 1  # partner's connection fetched once for both
    clock.advance(seconds=21)
    await now_playing(owner_client)
    assert ctx.now_playing.upstream_calls == 2


async def test_demo_playback_is_labelled_and_fresh(
    owner_client: ApiClient, clock: FakeClock
) -> None:
    await owner_client.post("/api/v1/providers/demo/connect")
    playback = (await now_playing(owner_client))["me"]["playback"]
    assert playback["is_demo"] is True
    assert playback["experimental"] is False
    assert playback["is_stale"] is False
    assert playback["fetched_at"] is not None
    assert playback["last_changed_at"] is None  # nothing observed yet: unknown, not "now"
    assert playback["track_url"] is None


# ----- service-level behaviour with a controllable fake provider --------------------


class FakeProvider:
    name = "spotify"
    experimental = False

    def __init__(self) -> None:
        self.results: list[FetchResult | Exception] = []
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.credentials: list[Credentials] = []

    async def fetch_playback(self, credentials: Credentials, *, subject_key: str) -> FetchResult:
        self.calls += 1
        self.credentials.append(credentials)
        if self.gate is not None:
            await self.gate.wait()
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


def playing(title: str = "Song", progress: int = 1000) -> FetchResult:
    return FetchResult(
        ProviderPlayback(
            PlaybackStatus.PLAYING,
            content_type=ContentType.TRACK,
            track=TrackInfo(
                title=title, artist_names=("A",), duration_ms=100_000, provider_track_id=title
            ),
            progress_ms=progress,
        )
    )


@pytest.fixture
async def spotify_conn(ctx: AppContext, owner: Any) -> ConnectionRef:
    from app.models import ProviderName
    from app.services.provider_auth import store_connection

    async with ctx.session_factory() as db:
        conn, _ = await store_connection(
            db,
            ctx,
            user_id=owner.id,
            provider=ProviderName.SPOTIFY,
            tokens=TokenSet("access-1", "refresh-1", None, "user-read-currently-playing"),
        )
        await db.commit()
        return ConnectionRef(conn.id, conn.provider, conn.status, conn.token_version)


@pytest.fixture
def fake(ctx: AppContext) -> FakeProvider:
    provider = FakeProvider()
    ctx.providers._by_name[provider.name] = provider  # type: ignore[index,assignment]
    return provider


async def test_single_flight(
    ctx: AppContext, spotify_conn: ConnectionRef, fake: FakeProvider
) -> None:
    fake.results = [playing()]
    fake.gate = asyncio.Event()
    tasks = [asyncio.create_task(ctx.now_playing.playback_for(spotify_conn)) for _ in range(5)]
    await asyncio.sleep(0.05)
    fake.gate.set()
    views = await asyncio.gather(*tasks)
    assert fake.calls == 1
    assert {v.track.title for v in views if v.track} == {"Song"}
    assert fake.credentials[0].access_token == "access-1"  # decrypted only for the call


async def test_transient_error_serves_stale_then_backs_off(
    ctx: AppContext, spotify_conn: ConnectionRef, fake: FakeProvider, clock: FakeClock
) -> None:
    fake.results = [playing("First")]
    first = await ctx.now_playing.playback_for(spotify_conn)
    assert first.status is PlaybackStatus.PLAYING
    assert first.progress_ms == 1000

    clock.advance(seconds=21)
    fake.results = [ProviderError("provider_rate_limited", retry_after_seconds=120)]
    stale = await ctx.now_playing.playback_for(spotify_conn)
    assert stale.is_stale is True
    assert stale.track is not None
    assert stale.track.title == "First"
    assert stale.progress_ms is None  # never extrapolate from stale data
    assert stale.detail_code == "provider_rate_limited"
    assert fake.calls == 2

    clock.advance(seconds=60)  # still inside Retry-After: no upstream call
    again = await ctx.now_playing.playback_for(spotify_conn)
    assert again.is_stale
    assert fake.calls == 2

    clock.advance(seconds=300)  # stale data older than 5 min is dropped
    fake.results = [ProviderError("provider_unreachable")]
    gone = await ctx.now_playing.playback_for(spotify_conn)
    assert gone.status is PlaybackStatus.UNAVAILABLE
    assert gone.track is None
    assert fake.calls == 3

    async with ctx.session_factory() as db:
        row = (await db.execute(select(ProviderConnection))).scalar_one()
    assert row.last_error_code == "provider_unreachable"
    assert row.consecutive_failures == 2
    assert row.backoff_until == clock.now + __import__("datetime").timedelta(seconds=30)


async def test_reauth_required_is_persisted_and_stops_calls(
    ctx: AppContext, spotify_conn: ConnectionRef, fake: FakeProvider
) -> None:
    fake.results = [ProviderError("provider_reauth_required", reauth_required=True)]
    view = await ctx.now_playing.playback_for(spotify_conn)
    assert view.status is PlaybackStatus.ERROR
    assert view.detail_code == "provider_reauth_required"
    async with ctx.session_factory() as db:
        row = (await db.execute(select(ProviderConnection))).scalar_one()
    assert row.status == ConnectionStatus.REAUTH_REQUIRED.value
    again = await ctx.now_playing.playback_for(
        ConnectionRef(spotify_conn.id, "spotify", row.status, row.token_version)
    )
    assert again.detail_code == "provider_reauth_required"
    assert fake.calls == 1


async def test_refreshed_tokens_are_persisted_encrypted(
    ctx: AppContext, spotify_conn: ConnectionRef, fake: FakeProvider, clock: FakeClock
) -> None:
    fake.results = [
        FetchResult(playing().playback, TokenSet("access-2", "refresh-2", clock.now, None))
    ]
    await ctx.now_playing.playback_for(spotify_conn)
    async with ctx.session_factory() as db:
        row = (await db.execute(select(ProviderConnection))).scalar_one()
    assert row.token_version == spotify_conn.token_version + 1
    assert "access-2" not in (row.access_token_enc or "")
    assert "refresh-2" not in (row.refresh_token_enc or "")
    clock.advance(seconds=21)
    fake.results = [playing()]
    await ctx.now_playing.playback_for(spotify_conn)
    assert fake.credentials[-1].access_token == "access-2"
    assert fake.credentials[-1].refresh_token == "refresh-2"


async def test_last_changed_at_tracks_observed_changes(
    ctx: AppContext, spotify_conn: ConnectionRef, fake: FakeProvider, clock: FakeClock
) -> None:
    fake.results = [playing("One")]
    assert (await ctx.now_playing.playback_for(spotify_conn)).last_changed_at is None
    clock.advance(seconds=21)
    fake.results = [playing("One", progress=21_000)]  # same song, later position
    assert (await ctx.now_playing.playback_for(spotify_conn)).last_changed_at is None
    clock.advance(seconds=21)
    fake.results = [playing("Two")]
    changed = await ctx.now_playing.playback_for(spotify_conn)
    assert changed.last_changed_at == clock.now


async def test_unexpected_exception_is_contained(
    ctx: AppContext, spotify_conn: ConnectionRef, fake: FakeProvider
) -> None:
    fake.results = [RuntimeError("access_token=LEAK")]
    view = await ctx.now_playing.playback_for(spotify_conn)
    assert view.status is PlaybackStatus.ERROR
    assert view.detail_code == "provider_bad_response"


async def test_disconnected_connection(ctx: AppContext, fake: FakeProvider) -> None:
    ghost = ConnectionRef(uuid.uuid4(), "spotify", "active", 1)
    view = await ctx.now_playing.playback_for(ghost)
    assert view.status is PlaybackStatus.NOT_CONNECTED
    assert fake.calls == 0
