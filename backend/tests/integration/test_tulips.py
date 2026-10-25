"""Tulips: authorisation, direction, unseen state, rate limits, retention, deletion."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.context import AppContext
from app.core.ratelimit import RateLimiter
from app.models import Tulip
from app.services import tulips
from app.services.maintenance import purge_expired
from tests.conftest import PARTNER_PASSWORD, ApiClient, FakeClock

TULIPS = "/api/v1/room/tulips"


async def tulip_count(ctx: AppContext) -> int:
    async with ctx.session_factory() as db:
        return int((await db.execute(select(func.count()).select_from(Tulip))).scalar_one())


async def listing(client: ApiClient) -> dict[str, Any]:
    response = await client.get(TULIPS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_send_and_receive(
    owner_client: ApiClient, partner_client: ApiClient, clock: FakeClock
) -> None:
    sent = await owner_client.post(TULIPS)
    assert sent.status_code == 201, sent.text
    assert sent.json()["direction"] == "sent"
    assert sent.json()["is_new"] is False
    clock.advance(seconds=5)
    second = await owner_client.post(TULIPS)
    assert second.status_code == 201

    received = await listing(partner_client)
    assert received["unseen_count"] == 2
    assert [t["id"] for t in received["items"]] == [second.json()["id"], sent.json()["id"]]
    assert {t["direction"] for t in received["items"]} == {"received"}
    assert all(t["is_new"] for t in received["items"])

    # The sender sees what they sent, but never whether it has been seen.
    mine = await listing(owner_client)
    assert mine["unseen_count"] == 0
    assert {t["direction"] for t in mine["items"]} == {"sent"}
    assert not any(t["is_new"] for t in mine["items"])
    assert "seen_at" not in str(mine)

    seen = await partner_client.post(f"{TULIPS}/seen")
    assert seen.status_code == 200
    assert seen.json()["unseen_count"] == 0
    assert not any(t["is_new"] for t in seen.json()["items"])
    assert (await listing(owner_client))["items"] == mine["items"]  # no read receipts


async def test_nothing_written_by_the_sender_is_stored(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    sent = await owner_client.post(TULIPS, json={"message": "<script>alert(1)</script>"})
    assert sent.status_code == 201
    received = await listing(partner_client)
    assert "script" not in str(received)
    assert set(received["items"][0]) == {"id", "direction", "created_at", "is_new"}


async def test_needs_a_partner_auth_and_csrf(owner_client: ApiClient, make_client: Any) -> None:
    alone = await owner_client.post(TULIPS)
    assert alone.status_code == 409
    assert alone.json()["error"]["code"] == "no_partner"
    assert (await listing(owner_client))["items"] == []

    stranger: ApiClient = make_client()
    assert (await stranger.get(TULIPS)).status_code == 401
    assert (await stranger.post(TULIPS)).status_code == 401
    no_token = await owner_client.http.post(TULIPS)
    assert no_token.status_code == 403
    assert no_token.json()["error"]["code"] == "csrf_failed"


def limiter_on_fake_time(ctx: AppContext, clock: FakeClock) -> None:
    ctx.rate_limiter = RateLimiter(monotonic=lambda: clock.now.timestamp())


async def test_rate_limited(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext, clock: FakeClock
) -> None:
    del partner_client
    limiter_on_fake_time(ctx, clock)
    for _ in range(10):
        assert (await owner_client.post(TULIPS)).status_code == 201
    limited = await owner_client.post(TULIPS)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    clock.advance(seconds=61)  # the per-minute window is per sender and slides
    assert (await owner_client.post(TULIPS)).status_code == 201


async def test_retention_keeps_twenty_and_seven_days(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext, clock: FakeClock
) -> None:
    limiter_on_fake_time(ctx, clock)
    for _ in range(25):
        clock.advance(seconds=30)  # stay under the per-minute limit
        assert (await partner_client.post(TULIPS)).status_code == 201
    assert await tulip_count(ctx) == tulips.MAX_PER_ROOM
    assert len((await listing(owner_client))["items"]) == tulips.MAX_PER_ROOM

    clock.advance(days=8)
    assert (await listing(owner_client))["items"] == []  # expired ones are never shown
    async with ctx.session_factory() as db:
        await purge_expired(db, clock)
    assert await tulip_count(ctx) == 0


async def test_deleting_an_account_deletes_their_tulips(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext, clock: FakeClock
) -> None:
    await owner_client.post(TULIPS)
    clock.advance(seconds=1)
    await partner_client.post(TULIPS)
    assert await tulip_count(ctx) == 2
    deleted = await partner_client.delete("/api/v1/me", json={"password": PARTNER_PASSWORD})
    assert deleted.status_code == 204
    assert await tulip_count(ctx) == 0
    assert (await listing(owner_client))["items"] == []
