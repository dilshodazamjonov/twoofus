"""Disconnecting or deleting an account drops our copy of the credentials and,
where the provider supports it (Yandex ID), revokes the grant itself."""

from __future__ import annotations

from typing import Any

import httpx
import respx
from sqlalchemy import select

from app.context import AppContext
from app.models import ProviderConnection
from app.providers.spotify import TOKEN_URL
from app.providers.yandex import YandexToken
from tests.conftest import (
    OWNER_PASSWORD,
    PARTNER_PASSWORD,
    ApiClient,
    FakeClock,
    FakeYandexGateway,
)


async def connect_yandex(
    client: ApiClient, gateway: FakeYandexGateway, clock: FakeClock, token: str
) -> None:
    started = await client.post("/api/v1/providers/yandex/device-authorization")
    assert started.status_code == 201, started.text
    gateway.poll_results = [YandexToken(token, 31_536_000)]
    clock.advance(seconds=5)
    done = (await client.post("/api/v1/providers/yandex/device-authorization/poll")).json()
    assert done["status"] == "completed"


async def test_yandex_disconnect_revokes_the_token(
    owner_client: ApiClient, yandex_gateway: FakeYandexGateway, clock: FakeClock, ctx: AppContext
) -> None:
    await connect_yandex(owner_client, yandex_gateway, clock, "TOKEN-A")
    response = await owner_client.delete("/api/v1/providers/connection")
    assert response.json() == {"provider": "yandex", "provider_revocation": "revoked"}
    assert yandex_gateway.revoked == ["TOKEN-A"]
    async with ctx.session_factory() as db:
        assert (await db.execute(select(ProviderConnection))).first() is None


async def test_revocation_failure_still_deletes_our_copy(
    owner_client: ApiClient, yandex_gateway: FakeYandexGateway, clock: FakeClock, ctx: AppContext
) -> None:
    await connect_yandex(owner_client, yandex_gateway, clock, "TOKEN-A")
    yandex_gateway.revoke_result = False
    response = await owner_client.delete("/api/v1/providers/connection")
    assert response.json()["provider_revocation"] == "failed"
    await connect_yandex(owner_client, yandex_gateway, clock, "TOKEN-B")
    yandex_gateway.revoke_result = RuntimeError("library changed")
    response = await owner_client.delete("/api/v1/providers/connection")
    assert response.status_code == 200
    assert response.json()["provider_revocation"] == "failed"
    async with ctx.session_factory() as db:
        assert (await db.execute(select(ProviderConnection))).first() is None


async def test_reconnecting_revokes_the_replaced_token_only_if_it_changed(
    owner_client: ApiClient, yandex_gateway: FakeYandexGateway, clock: FakeClock
) -> None:
    await connect_yandex(owner_client, yandex_gateway, clock, "TOKEN-A")
    await connect_yandex(owner_client, yandex_gateway, clock, "TOKEN-A")  # same device, same token
    assert yandex_gateway.revoked == []
    await connect_yandex(owner_client, yandex_gateway, clock, "TOKEN-B")
    assert yandex_gateway.revoked == ["TOKEN-A"]
    # Switching to another service revokes the Yandex grant too.
    await owner_client.post("/api/v1/providers/demo/connect")
    assert yandex_gateway.revoked == ["TOKEN-A", "TOKEN-B"]


@respx.mock
async def test_spotify_has_no_revocation_api(owner_client: ApiClient) -> None:
    from urllib.parse import parse_qs, urlsplit

    authorize = await owner_client.post("/api/v1/providers/spotify/authorize")
    state = parse_qs(urlsplit(authorize.json()["authorization_url"]).query)["state"][0]
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "sp-a", "token_type": "Bearer", "expires_in": 3600},
        )
    )
    await owner_client.get(
        "/api/v1/providers/spotify/callback", params={"state": state, "code": "c"}
    )
    response = await owner_client.delete("/api/v1/providers/connection")
    assert response.json() == {"provider": "spotify", "provider_revocation": "not_supported"}
    assert len(respx.calls) == 1  # the code exchange only: nothing else was called


async def test_deleting_an_account_revokes_its_yandex_grant(
    owner_client: ApiClient,
    partner_client: ApiClient,
    yandex_gateway: FakeYandexGateway,
    clock: FakeClock,
    ctx: AppContext,
) -> None:
    await connect_yandex(partner_client, yandex_gateway, clock, "PARTNER-TOKEN")
    gone = await partner_client.delete("/api/v1/me", json={"password": PARTNER_PASSWORD})
    assert gone.status_code == 204
    assert yandex_gateway.revoked == ["PARTNER-TOKEN"]
    async with ctx.session_factory() as db:
        assert (await db.execute(select(ProviderConnection))).first() is None
    assert (await owner_client.get("/api/v1/me")).status_code == 200
    assert OWNER_PASSWORD  # the owner keeps their account


async def test_a_pending_device_code_cannot_be_used_by_the_other_member(
    owner_client: ApiClient,
    partner_client: ApiClient,
    yandex_gateway: FakeYandexGateway,
    clock: FakeClock,
    ctx: AppContext,
    make_client: Any,
) -> None:
    started = await owner_client.post("/api/v1/providers/yandex/device-authorization")
    assert started.status_code == 201
    yandex_gateway.poll_results = [YandexToken("STOLEN?", 100)]
    clock.advance(seconds=5)
    # The partner has no flow of her own: polling never reaches the owner's.
    foreign = await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    assert foreign.status_code == 404
    assert yandex_gateway.calls["poll"] == 0
    cancel = await partner_client.delete("/api/v1/providers/yandex/device-authorization")
    assert cancel.status_code == 404
    async with ctx.session_factory() as db:
        assert (await db.execute(select(ProviderConnection))).first() is None
    # The owner's own session still completes it.
    done = (await owner_client.post("/api/v1/providers/yandex/device-authorization/poll")).json()
    assert done["status"] == "completed"
    async with ctx.session_factory() as db:
        conn = (await db.execute(select(ProviderConnection))).scalar_one()
    owner_id = (await owner_client.get("/api/v1/me")).json()["id"]
    assert str(conn.user_id) == owner_id
