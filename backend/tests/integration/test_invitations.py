from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.context import AppContext
from app.core.security import hash_token
from app.models import Invitation
from tests.conftest import PARTNER_PASSWORD, ApiClient, FakeClock


def accept_body(token: str, username: str = "amira") -> dict[str, str]:
    return {
        "token": token,
        "username": username,
        "display_name": "Amira",
        "password": PARTNER_PASSWORD,
    }


async def test_full_invitation_flow(
    owner_client: ApiClient, make_client: Any, ctx: AppContext
) -> None:
    created = await owner_client.post("/api/v1/invitations")
    assert created.status_code == 201
    data = created.json()
    token = data["token"]
    assert data["invite_url"] == f"http://127.0.0.1:3000/invite#token={token}"

    async with ctx.session_factory() as db:
        stored = (await db.execute(select(Invitation))).scalar_one()
    assert stored.token_hash == hash_token(token)  # only the hash is stored
    assert token not in stored.token_hash

    status = (await owner_client.get("/api/v1/invitations/current")).json()
    assert status["pending"] is True

    partner: ApiClient = make_client()
    inspect = await partner.post("/api/v1/invitations/inspect", json={"token": token})
    assert inspect.status_code == 200
    assert inspect.json()["inviter_display_name"] == "Khaled"

    accepted = await partner.post("/api/v1/invitations/accept", json=accept_body(token))
    assert accepted.status_code == 201
    assert accepted.json()["user"]["role"] == "partner"
    room = (await partner.get("/api/v1/room")).json()
    assert [m["display_name"] for m in room["members"]] == ["Amira", "Khaled"]
    assert room["invitation"] is None  # partners don't see invitation state

    reuse = await make_client().post(
        "/api/v1/invitations/accept", json=accept_body(token, "mallory")
    )
    assert reuse.status_code == 400
    assert reuse.json()["error"]["code"] == "invitation_invalid"
    assert (await owner_client.get("/api/v1/invitations/current")).json()["pending"] is False


async def test_partner_cannot_invite_and_room_is_capped_at_two(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    forbidden = await partner_client.post("/api/v1/invitations")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "owner_only"
    full = await owner_client.post("/api/v1/invitations")
    assert full.status_code == 409
    assert full.json()["error"]["code"] == "room_full"


async def test_invitation_expiry_revocation_and_replacement(
    owner_client: ApiClient, make_client: Any, clock: FakeClock
) -> None:
    first = (await owner_client.post("/api/v1/invitations")).json()["token"]
    second = (await owner_client.post("/api/v1/invitations")).json()["token"]
    partner: ApiClient = make_client()
    old = await partner.post("/api/v1/invitations/inspect", json={"token": first})
    assert old.status_code == 400  # issuing a new invitation revoked the old one

    assert (await owner_client.delete("/api/v1/invitations/current")).status_code == 204
    revoked = await partner.post("/api/v1/invitations/accept", json=accept_body(second))
    assert revoked.status_code == 400

    third = (await owner_client.post("/api/v1/invitations")).json()["token"]
    clock.advance(hours=49)  # INVITE_TTL_HOURS=48
    expired = await partner.post("/api/v1/invitations/accept", json=accept_body(third))
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "invitation_invalid"


async def test_concurrent_accepts_only_one_wins(owner_client: ApiClient, make_client: Any) -> None:
    token = (await owner_client.post("/api/v1/invitations")).json()["token"]
    a: ApiClient = make_client()
    b: ApiClient = make_client()
    await a.csrf()
    await b.csrf()
    results = await asyncio.gather(
        a.post("/api/v1/invitations/accept", json=accept_body(token, "first")),
        b.post("/api/v1/invitations/accept", json=accept_body(token, "second")),
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 400], [r.text for r in results]
    room = (await owner_client.get("/api/v1/room")).json()
    assert len(room["members"]) == 2


async def test_accept_validation_and_username_conflict(
    owner_client: ApiClient, make_client: Any
) -> None:
    token = (await owner_client.post("/api/v1/invitations")).json()["token"]
    client: ApiClient = make_client()
    weak = await client.post(
        "/api/v1/invitations/accept",
        json={"token": token, "username": "amira", "display_name": "A", "password": "aaaaaaaaaaaa"},
    )
    assert weak.status_code == 422
    assert weak.json()["error"]["code"] == "weak_password"
    taken = await client.post("/api/v1/invitations/accept", json=accept_body(token, "KHALED"))
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "username_taken"
    # The failed attempts rolled back; the invitation still works.
    ok = await client.post("/api/v1/invitations/accept", json=accept_body(token))
    assert ok.status_code == 201


async def test_cannot_accept_while_signed_in(owner_client: ApiClient) -> None:
    token = (await owner_client.post("/api/v1/invitations")).json()["token"]
    response = await owner_client.post("/api/v1/invitations/accept", json=accept_body(token))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_signed_in"


async def test_invite_endpoints_are_rate_limited(owner_client: ApiClient, make_client: Any) -> None:
    client: ApiClient = make_client()
    for _ in range(15):
        await client.post("/api/v1/invitations/inspect", json={"token": "x" * 43})
    limited = await client.post("/api/v1/invitations/inspect", json={"token": "x" * 43})
    assert limited.status_code == 429
