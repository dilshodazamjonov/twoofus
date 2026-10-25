"""Provider authorisation flows end to end (Spotify mocked with respx,
Yandex with the fake gateway) plus privacy guarantees around them."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import respx
from sqlalchemy import select

from app.context import AppContext
from app.models import AuthFlowStatus, ProviderAuthFlow, ProviderConnection
from app.providers.base import ProviderError
from app.providers.spotify import CURRENTLY_PLAYING_URL, TOKEN_URL
from app.providers.yandex import DeviceFlowError, DeviceFlowPending, YandexToken, YandexTrackMeta
from tests.conftest import (
    OWNER_PASSWORD,
    SPOTIFY_REDIRECT,
    ApiClient,
    FakeClock,
    FakeYandexGateway,
    enable_sharing,
    yandex_playing,
)
from tests.unit.test_spotify_provider import track_body

TOKEN_JSON = {
    "access_token": "SPOTIFY-ACCESS-PLAINTEXT",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "SPOTIFY-REFRESH-PLAINTEXT",
    "scope": "user-read-currently-playing",
}


async def start_spotify(client: ApiClient) -> dict[str, str]:
    response = await client.post("/api/v1/providers/spotify/authorize")
    assert response.status_code == 200, response.text
    url = response.json()["authorization_url"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert query["redirect_uri"] == SPOTIFY_REDIRECT
    assert query["scope"] == "user-read-currently-playing"
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43
    return query


async def callback(client: ApiClient, **params: str) -> httpx.Response:
    return await client.get("/api/v1/providers/spotify/callback", params=params)


@respx.mock
async def test_spotify_connect_and_now_playing(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext
) -> None:
    token_route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))
    respx.get(CURRENTLY_PLAYING_URL).mock(return_value=httpx.Response(200, json=track_body()))

    query = await start_spotify(owner_client)
    response = await callback(owner_client, code="auth-code", state=query["state"])
    assert response.status_code == 303
    assert response.headers["location"] == "/connect?connect=spotify&result=connected"
    sent = parse_qs(token_route.calls.last.request.content.decode())
    assert sent["code"] == ["auth-code"]
    assert len(sent["code_verifier"][0]) >= 43

    async with ctx.session_factory() as db:
        conn = (await db.execute(select(ProviderConnection))).scalar_one()
        flow = (await db.execute(select(ProviderAuthFlow))).scalar_one()
    assert conn.provider == "spotify"
    assert conn.scopes == "user-read-currently-playing"
    assert "PLAINTEXT" not in (conn.access_token_enc or "") + (conn.refresh_token_enc or "")
    assert flow.status == AuthFlowStatus.COMPLETED.value
    assert flow.secret_enc is None

    providers = (await owner_client.get("/api/v1/providers")).json()
    assert providers["connection"]["provider"] == "spotify"
    assert providers["connection"]["reauthorize_by"] is not None

    await enable_sharing(owner_client)
    seen_by_partner = await partner_client.get("/api/v1/room/now-playing")
    playback = seen_by_partner.json()["partner"]["playback"]
    assert playback["source"] == "spotify"
    assert playback["status"] == "playing"
    assert playback["track_title"] == "Song Title"
    assert playback["track_url"].startswith("https://open.spotify.com/")

    # No response anywhere contains a token.
    for client in (owner_client, partner_client):
        for path in ("/api/v1/room", "/api/v1/room/now-playing", "/api/v1/providers", "/api/v1/me"):
            text = (await client.get(path)).text
            assert "PLAINTEXT" not in text
            assert "auth-code" not in text


@respx.mock
async def test_spotify_callback_rejections(
    owner_client: ApiClient, partner_client: ApiClient, make_client: Any, clock: FakeClock
) -> None:
    token_route = respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=TOKEN_JSON))

    bad = await callback(owner_client, code="c", state="not-a-real-state")
    assert bad.headers["location"].endswith("result=invalid_state")

    # A callback arriving in another person's session is refused (login CSRF).
    query = await start_spotify(owner_client)
    hijack = await callback(partner_client, code="c", state=query["state"])
    assert hijack.headers["location"].endswith("result=session_mismatch")
    # ...and the state cannot be reused afterwards.
    retry = await callback(owner_client, code="c", state=query["state"])
    assert retry.headers["location"].endswith("result=invalid_state")

    anonymous: ApiClient = make_client()
    query = await start_spotify(owner_client)
    no_session = await callback(anonymous, code="c", state=query["state"])
    assert no_session.headers["location"].endswith("result=session_mismatch")

    query = await start_spotify(owner_client)
    denied = await callback(owner_client, error="access_denied", state=query["state"])
    assert denied.headers["location"].endswith("result=access_denied")

    query = await start_spotify(owner_client)
    clock.advance(minutes=11)
    expired = await callback(owner_client, code="c", state=query["state"])
    assert expired.headers["location"].endswith("result=invalid_state")

    assert token_route.call_count == 0
    assert (await owner_client.get("/api/v1/providers")).json()["connection"] is None


@respx.mock
async def test_spotify_code_exchange_failure(owner_client: ApiClient) -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    query = await start_spotify(owner_client)
    response = await callback(owner_client, code="c", state=query["state"])
    assert response.headers["location"].endswith("result=failed")


async def test_spotify_not_configured(make_client: Any, owner: Any, app: Any) -> None:
    app.state.ctx.providers.spotify = None
    app.state.ctx.providers._by_name.pop("spotify", None)
    client: ApiClient = make_client()
    await client.login("khaled", OWNER_PASSWORD)
    response = await client.post("/api/v1/providers/spotify/authorize")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_not_available"


async def test_yandex_device_flow_happy_path(
    owner_client: ApiClient,
    partner_client: ApiClient,
    yandex_gateway: FakeYandexGateway,
    clock: FakeClock,
    ctx: AppContext,
) -> None:
    started = await partner_client.post("/api/v1/providers/yandex/device-authorization")
    assert started.status_code == 201
    flow = started.json()
    assert flow["status"] == "pending"
    assert flow["user_code"] == "ABCD-1234"
    assert flow["verification_url"] == "https://ya.ru/device"
    assert "SECRET" not in started.text  # the device code itself never leaves the server
    assert yandex_gateway.device_names == ["JustTheTwoOfUs"]

    # Polling early does not hit Yandex.
    early = await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    assert early.json()["status"] == "pending"
    assert yandex_gateway.calls["poll"] == 0

    yandex_gateway.poll_results = [
        None,
        DeviceFlowPending(slow_down=True),
        YandexToken("YANDEX-TOKEN-PLAINTEXT", 31_536_000),
    ]
    clock.advance(seconds=5)
    assert (await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")).json()[
        "status"
    ] == "pending"
    clock.advance(seconds=5)
    slow = (await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")).json()
    assert slow["poll_interval_seconds"] == 10
    clock.advance(seconds=10)
    done = await partner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    assert done.json()["status"] == "completed"
    assert done.json()["user_code"] is None
    assert yandex_gateway.calls["poll"] == 3

    async with ctx.session_factory() as db:
        conn = (await db.execute(select(ProviderConnection))).scalar_one()
    assert conn.provider == "yandex"
    assert conn.refresh_token_enc is None  # not stored: the library cannot use it
    assert "PLAINTEXT" not in (conn.access_token_enc or "")

    yandex_gateway.snapshot = yandex_playing()
    yandex_gateway.tracks["10994777"] = YandexTrackMeta(
        "Track", ("Artist",), "Album", "1193829", None, 200_000
    )
    await enable_sharing(partner_client)
    playback = (await owner_client.get("/api/v1/room/now-playing")).json()["partner"]["playback"]
    assert playback["source"] == "yandex"
    assert playback["experimental"] is True
    assert playback["status"] == "playing"
    assert playback["artist_names"] == ["Artist"]
    assert playback["track_url"] == "https://music.yandex.ru/album/1193829/track/10994777"
    assert yandex_gateway.tokens_seen == ["YANDEX-TOKEN-PLAINTEXT"]


async def test_yandex_device_flow_failures(
    owner_client: ApiClient, yandex_gateway: FakeYandexGateway, clock: FakeClock, make_client: Any
) -> None:
    await owner_client.post("/api/v1/providers/yandex/device-authorization")
    yandex_gateway.poll_results = [DeviceFlowError("denied")]
    clock.advance(seconds=5)
    denied = (await owner_client.post("/api/v1/providers/yandex/device-authorization/poll")).json()
    assert denied["status"] == "failed"
    assert denied["error_code"] == "denied"

    await owner_client.post("/api/v1/providers/yandex/device-authorization")
    clock.advance(seconds=301)
    expired = (await owner_client.post("/api/v1/providers/yandex/device-authorization/poll")).json()
    assert expired["status"] == "expired"

    await owner_client.post("/api/v1/providers/yandex/device-authorization")
    yandex_gateway.poll_results = [ProviderError("provider_unreachable")]
    clock.advance(seconds=5)
    transient = (
        await owner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    ).json()
    assert transient["status"] == "pending"  # network trouble does not kill the flow

    # The pending flow belongs to this browser session only.
    other_session: ApiClient = make_client()
    await other_session.login("khaled", OWNER_PASSWORD)
    foreign = await other_session.post("/api/v1/providers/yandex/device-authorization/poll")
    assert foreign.status_code == 404

    assert (
        await owner_client.delete("/api/v1/providers/yandex/device-authorization")
    ).status_code == 204
    cancelled = (
        await owner_client.post("/api/v1/providers/yandex/device-authorization/poll")
    ).json()
    assert cancelled["status"] == "cancelled"


async def test_yandex_start_failure_is_reported(
    owner_client: ApiClient, yandex_gateway: FakeYandexGateway
) -> None:
    async def boom(*, device_name: str, device_id: str) -> Any:
        raise ProviderError("provider_unreachable")

    yandex_gateway.request_device_code = boom  # type: ignore[method-assign]
    response = await owner_client.post("/api/v1/providers/yandex/device-authorization")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unreachable"


async def test_disconnect_deletes_credentials(owner_client: ApiClient, ctx: AppContext) -> None:
    await owner_client.post("/api/v1/providers/demo/connect")
    response = await owner_client.delete("/api/v1/providers/connection")
    assert response.status_code == 200
    assert response.json() == {"provider": "demo", "provider_revocation": "not_applicable"}
    async with ctx.session_factory() as db:
        assert (await db.execute(select(ProviderConnection))).first() is None
    playback = (await owner_client.get("/api/v1/room/now-playing")).json()["me"]["playback"]
    assert playback["status"] == "not_connected"


async def test_demo_disabled(owner: Any, make_client: Any, app: Any) -> None:
    app.state.ctx.providers.demo = None
    app.state.ctx.providers._by_name.pop("demo", None)
    client: ApiClient = make_client()
    await client.login("khaled", OWNER_PASSWORD)
    response = await client.post("/api/v1/providers/demo/connect")
    assert response.status_code == 503
