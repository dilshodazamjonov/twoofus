"""Authorization boundaries, data visibility between members, deletion."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.context import AppContext
from app.models import (
    AuthSession,
    ProviderConnection,
    Room,
    RoomMember,
    SharePreference,
    User,
)
from tests.conftest import OWNER_PASSWORD, PARTNER_PASSWORD, ApiClient, enable_sharing


async def count(ctx: AppContext, model: Any) -> int:
    async with ctx.session_factory() as db:
        return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


async def test_room_hides_partner_provider_unless_sharing(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    await partner_client.post("/api/v1/providers/demo/connect")
    members = (await owner_client.get("/api/v1/room")).json()["members"]
    partner = next(m for m in members if not m["is_me"])
    assert partner["sharing_enabled"] is False
    assert partner["provider"] is None
    await enable_sharing(partner_client)
    members = (await owner_client.get("/api/v1/room")).json()["members"]
    assert next(m for m in members if not m["is_me"])["provider"] == "demo"


async def test_provider_details_are_only_for_yourself(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    await partner_client.post("/api/v1/providers/demo/connect")
    mine = (await owner_client.get("/api/v1/providers")).json()
    assert mine["connection"] is None  # the partner's connection never shows up here
    theirs = (await partner_client.get("/api/v1/providers")).json()
    assert theirs["connection"]["provider"] == "demo"


async def test_partner_cannot_use_owner_only_routes(partner_client: ApiClient) -> None:
    for method, path in (
        ("POST", "/api/v1/invitations"),
        ("GET", "/api/v1/invitations/current"),
        ("DELETE", "/api/v1/invitations/current"),
    ):
        response = await partner_client.request(method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["error"]["code"] == "owner_only"


async def test_profile_update(owner_client: ApiClient) -> None:
    response = await owner_client.patch("/api/v1/me", json={"display_name": "  Kha   led "})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Kha led"
    bad = await owner_client.patch("/api/v1/me", json={"display_name": "   "})
    assert bad.status_code == 422


async def test_partner_deletes_account(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext
) -> None:
    await partner_client.post("/api/v1/providers/demo/connect")
    wrong = await partner_client.delete("/api/v1/me", json={"password": "nope-nope-nope"})
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "wrong_password"

    deleted = await partner_client.delete("/api/v1/me", json={"password": PARTNER_PASSWORD})
    assert deleted.status_code == 204
    assert (await partner_client.get("/api/v1/me")).status_code == 401
    assert await count(ctx, User) == 1
    assert await count(ctx, ProviderConnection) == 0
    assert await count(ctx, SharePreference) == 1
    async with ctx.session_factory() as db:
        sessions = (await db.execute(select(AuthSession.user_id).distinct())).scalars().all()
    assert len(sessions) == 1  # only the owner's sessions remain

    room = (await owner_client.get("/api/v1/room")).json()
    assert len(room["members"]) == 1
    assert (await owner_client.post("/api/v1/invitations")).status_code == 201  # can invite again


async def test_owner_deletes_account_partner_becomes_owner(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext
) -> None:
    assert (
        await owner_client.delete("/api/v1/me", json={"password": OWNER_PASSWORD})
    ).status_code == 204
    me = (await partner_client.get("/api/v1/me")).json()
    assert me["role"] == "owner"
    assert await count(ctx, Room) == 1
    assert await count(ctx, RoomMember) == 1


async def test_last_member_deleting_removes_the_room(
    owner_client: ApiClient, ctx: AppContext
) -> None:
    assert (
        await owner_client.delete("/api/v1/me", json={"password": OWNER_PASSWORD})
    ).status_code == 204
    assert await count(ctx, Room) == 0
    assert await count(ctx, User) == 0
    assert await count(ctx, AuthSession) == 0


async def test_account_deletion_rate_limited(owner_client: ApiClient) -> None:
    for _ in range(10):
        await owner_client.delete("/api/v1/me", json={"password": "wrong-password"})
    limited = await owner_client.delete("/api/v1/me", json={"password": OWNER_PASSWORD})
    assert limited.status_code == 429
