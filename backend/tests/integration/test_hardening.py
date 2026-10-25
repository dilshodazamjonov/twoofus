"""Phase 3 hardening: proxy authentication, body limits, request ids, 500s,
rate limits on the remaining writes, structured logs, key re-encryption."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.cli import reencrypt
from app.context import AppContext
from app.core.crypto import TokenCipher, generate_key
from app.core.logging import JsonFormatter, RedactingFilter
from app.core.middleware import MAX_BODY_BYTES, PROXY_AUTH_HEADER
from app.core.ratelimit import Limit
from app.models import ProviderAuthFlow, ProviderConnection, ProviderName
from app.providers.base import TokenSet
from app.services.credentials import flow_context, token_context
from app.services.provider_auth import start_spotify, store_connection
from tests.conftest import APP_ORIGIN, ApiClient, make_settings

PROXY_SECRET = "proxy-" + "s" * 40

# ----- proxy authentication -------------------------------------------------------------


class TestProxyAuth:
    @pytest.fixture
    def settings_overrides(self) -> dict[str, Any]:
        return {"proxy_shared_secret": PROXY_SECRET}

    async def test_requests_without_the_proxy_secret_are_refused(
        self, make_client: Any, owner: Any
    ) -> None:
        direct: ApiClient = make_client()
        refused = await direct.get("/api/v1/config")
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "proxy_required"
        assert refused.headers["x-content-type-options"] == "nosniff"
        wrong = await direct.get("/api/v1/config", headers={PROXY_AUTH_HEADER: "nope"})
        assert wrong.status_code == 403
        # Liveness stays open for the container health check (it reveals nothing).
        assert (await direct.get("/api/v1/health")).status_code == 200

        proxied: ApiClient = make_client()
        proxied.http.headers[PROXY_AUTH_HEADER] = PROXY_SECRET
        assert (await proxied.get("/api/v1/config")).status_code == 200
        assert (await proxied.login("khaled", "owner-password-123")).status_code == 200
        assert (await proxied.get("/api/v1/me")).status_code == 200


# ----- request bodies, ids, errors ------------------------------------------------------


async def test_oversized_bodies_are_rejected_before_parsing(owner_client: ApiClient) -> None:
    big = {"username": "x" * (MAX_BODY_BYTES + 10), "password": "y"}
    response = await owner_client.post("/api/v1/auth/login", json=big)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.headers["cache-control"] == "no-store"

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(MAX_BODY_BYTES // 1024 + 2):
            yield b" " * 1024

    chunked = await owner_client.post(
        "/api/v1/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert chunked.status_code == 413

    async def small() -> AsyncIterator[bytes]:
        yield b'{"display_name": '
        yield b'"Khaled the Second"}'

    ok = await owner_client.patch(
        "/api/v1/me", content=small(), headers={"Content-Type": "application/json"}
    )
    assert ok.status_code == 200
    assert ok.json()["display_name"] == "Khaled the Second"


async def test_bad_content_length_is_rejected(make_client: Any) -> None:
    client: ApiClient = make_client()
    response = await client.post(
        "/api/v1/auth/login", headers={"Content-Length": "abc"}, content=b"{}"
    )
    assert response.status_code == 400


async def test_request_ids_are_returned_and_validated(make_client: Any) -> None:
    client: ApiClient = make_client()
    plain = await client.get("/api/v1/health")
    assert len(plain.headers["x-request-id"]) == 16
    echoed = await client.get("/api/v1/health", headers={"X-Request-ID": "caddy-1234abcd"})
    assert echoed.headers["x-request-id"] == "caddy-1234abcd"
    junk = await client.get("/api/v1/health", headers={"X-Request-ID": "<script>alert(1)"})
    assert junk.headers["x-request-id"] != "<script>alert(1)"


async def test_unexpected_errors_are_json_without_details(app: FastAPI) -> None:
    async def boom() -> None:
        raise RuntimeError("secret detail access_token=abc123")

    app.add_api_route("/api/v1/_test_boom", boom)
    # Starlette answers, then re-raises for the server to log; don't surface that here.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=APP_ORIGIN) as client:
        response = await client.get("/api/v1/_test_boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret detail" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


# ----- rate limits on the remaining state-changing endpoints ------------------------------


@pytest.mark.parametrize(
    ("limit_name", "method", "path", "body"),
    [
        ("CONNECT_PER_USER", "POST", "/api/v1/providers/spotify/authorize", None),
        ("CONNECT_PER_USER", "POST", "/api/v1/providers/yandex/device-authorization", None),
        ("SETTINGS_PER_USER", "PATCH", "/api/v1/me", {"display_name": "Khaled"}),
        ("SETTINGS_PER_USER", "PUT", "/api/v1/me/sharing", {"share_now_playing": False}),
        ("INVITE_CREATE_PER_USER", "POST", "/api/v1/invitations", None),
    ],
)
async def test_writes_are_rate_limited(
    owner_client: ApiClient,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    method: str,
    path: str,
    body: Any,
) -> None:
    from app.api.routes import invitations, me, providers

    for module in (providers, me, invitations):
        if hasattr(module, limit_name):
            monkeypatch.setattr(module, limit_name, Limit(attempts=3, window_seconds=60))
    for _ in range(3):
        ok = await owner_client.request(method, path, json=body)
        assert ok.status_code < 400, ok.text
    limited = await owner_client.request(method, path, json=body)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


async def test_device_poll_is_rate_limited(
    owner_client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes import providers

    monkeypatch.setattr(providers, "DEVICE_POLL_PER_USER", Limit(attempts=2, window_seconds=60))
    await owner_client.post("/api/v1/providers/yandex/device-authorization")
    path = "/api/v1/providers/yandex/device-authorization/poll"
    assert (await owner_client.post(path)).status_code == 200
    assert (await owner_client.post(path)).status_code == 200
    assert (await owner_client.post(path)).status_code == 429


# ----- structured logs ----------------------------------------------------------------------


def test_json_logs_are_redacted_and_only_carry_known_fields() -> None:
    record = logging.LogRecord(
        "app.request", logging.INFO, __file__, 1, "GET %s -> %d", ("/x?code=abc", 200), None
    )
    record.__dict__.update(
        {"request_id": "abcd1234abcd1234", "http_status": 200, "password": "hunter2-secret"}
    )
    assert RedactingFilter().filter(record)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["msg"] == "GET /x?code=[REDACTED] -> 200"
    assert entry["request_id"] == "abcd1234abcd1234"
    assert entry["http_status"] == 200
    assert "password" not in entry
    assert entry["level"] == "INFO"
    assert entry["ts"].endswith("+00:00")

    try:
        raise ValueError("refresh_token=SECRET-VALUE")
    except ValueError:
        failure = logging.LogRecord(
            "app", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    assert RedactingFilter().filter(failure)
    rendered = JsonFormatter().format(failure)
    assert "SECRET-VALUE" not in rendered
    assert "refresh_token=[REDACTED]" in json.loads(rendered)["exc"]


# ----- key rotation: bulk re-encryption --------------------------------------------------------


async def test_reencrypt_moves_everything_to_the_new_key(
    database_url: str, ctx: AppContext, owner_client: ApiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.UUID((await owner_client.get("/api/v1/me")).json()["id"])
    async with ctx.session_factory() as db:
        await store_connection(
            db,
            ctx,
            user_id=user_id,
            provider=ProviderName.SPOTIFY,
            tokens=TokenSet("ACCESS-PLAIN", "REFRESH-PLAIN", None, None),
        )
        await db.commit()
    me_session = (await owner_client.get("/api/v1/me/sessions")).json()["sessions"][0]["id"]
    async with ctx.session_factory() as db:
        await start_spotify(db, ctx, user_id=user_id, session_id=uuid.UUID(me_session))

    current_keys = ctx.settings.token_encryption_keys.get_secret_value()
    new_key = generate_key()
    rotated_settings = make_settings(
        database_url, token_encryption_keys=f"{new_key},{current_keys}"
    )
    monkeypatch.setattr(reencrypt, "get_settings", lambda: rotated_settings)

    dry = await reencrypt.reencrypt_all(dry_run=True)
    assert (dry.reencrypted, dry.undecryptable) == (3, 0)  # access, refresh, verifier
    report = await reencrypt.reencrypt_all(dry_run=False)
    assert (report.reencrypted, report.already_current, report.undecryptable) == (3, 0, 0)
    again = await reencrypt.reencrypt_all(dry_run=False)
    assert (again.reencrypted, again.already_current) == (0, 3)

    only_new = TokenCipher([rotated_settings.encryption_keys()[0]])
    async with ctx.session_factory() as db:
        conn = (await db.execute(select(ProviderConnection))).scalar_one()
        flow = (
            await db.execute(
                select(ProviderAuthFlow).where(ProviderAuthFlow.secret_enc.is_not(None))
            )
        ).scalar_one()
    access = only_new.decrypt(
        conn.access_token_enc or "", context=token_context(conn.user_id, conn.provider, "access")
    )
    assert access == "ACCESS-PLAIN"
    assert only_new.decrypt(flow.secret_enc or "", context=flow_context(flow.id, "code_verifier"))

    # A value no configured key can read is reported (exit code 1), never dropped.
    async with ctx.session_factory() as db:
        conn = (await db.execute(select(ProviderConnection))).scalar_one()
        conn.refresh_token_enc = "v1.deadbeef.AAAA"
        await db.commit()
    # The CLI uses asyncio.run(); keep it off the test's running event loop.
    assert await asyncio.to_thread(reencrypt.main, []) == 1


def test_reencrypt_cli_reports_bad_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.core.config import ConfigError

    def bad() -> Any:
        raise ConfigError("Invalid configuration: SECRET_KEY")

    monkeypatch.setattr(reencrypt, "get_settings", bad)
    assert reencrypt.main(["--dry-run"]) == 2
    assert "SECRET_KEY" in capsys.readouterr().err
