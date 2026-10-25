from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from app.auth import sessions
from app.auth.sessions import ROTATION_GRACE
from app.context import AppContext
from app.core.security import hash_token
from app.models import AuthSession
from tests.conftest import OWNER_PASSWORD, ApiClient, FakeClock

pytestmark = pytest.mark.usefixtures("owner")


def replayer(make_client: Any, **cookies: str) -> ApiClient:
    """A separate browser holding (possibly stale or stolen) cookies."""
    client: ApiClient = make_client()
    for name, value in cookies.items():
        client.http.cookies.set(name, value)
    return client


async def test_health_ready_and_config_have_no_secrets(make_client: Any, ctx: AppContext) -> None:
    client: ApiClient = make_client()
    assert (await client.get("/api/v1/health")).json() == {"status": "ok"}
    ready = await client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok", "migrations": "ok"}
    config = await client.get("/api/v1/config")
    assert config.status_code == 200
    body = config.text
    for secret in (
        ctx.settings.secret_key.get_secret_value(),
        ctx.settings.token_encryption_keys.get_secret_value(),
        ctx.settings.spotify_client_id,
    ):
        assert secret not in body
    data = config.json()
    assert data["providers"]["yandex"] == {"available": True, "experimental": True}
    assert data["providers"]["spotify"]["available"] is True
    assert config.headers["cache-control"] == "no-store"
    assert config.headers["x-content-type-options"] == "nosniff"


async def test_openapi_is_valid(make_client: Any) -> None:
    client: ApiClient = make_client()
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert spec["openapi"].startswith("3.")
    assert "/api/v1/room/now-playing" in spec["paths"]
    assert "/api/v1/providers/spotify/callback" in spec["paths"]


async def test_login_sets_hardened_session_cookie(make_client: Any) -> None:
    client: ApiClient = make_client()
    response = await client.login("Khaled", OWNER_PASSWORD)  # usernames are case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["role"] == "owner"
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("twoofus_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie
    csrf_cookie = next(c for c in cookies if c.startswith("twoofus_csrf="))
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=strict" in csrf_cookie
    me = await client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["username"] == "khaled"


async def test_wrong_password_and_unknown_user_look_identical(make_client: Any) -> None:
    client: ApiClient = make_client()
    wrong = await client.login("khaled", "not-the-password")
    unknown = await client.login("nobody", "not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    assert (
        wrong.json()
        == unknown.json()
        == {"error": {"code": "invalid_credentials", "message": "Wrong username or password."}}
    )


async def test_login_rate_limit(make_client: Any) -> None:
    client: ApiClient = make_client()
    for _ in range(10):
        assert (await client.login("khaled", "wrong-password")).status_code == 401
    limited = await client.login("khaled", OWNER_PASSWORD)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert limited.json()["error"]["code"] == "rate_limited"


async def test_unauthenticated_is_401_not_403(make_client: Any) -> None:
    client: ApiClient = make_client()
    for path in ("/api/v1/me", "/api/v1/room", "/api/v1/room/now-playing", "/api/v1/providers"):
        response = await client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "not_authenticated"


async def test_csrf_token_and_origin_are_required(
    owner_client: ApiClient, make_client: Any
) -> None:
    no_token = await owner_client.http.post("/api/v1/invitations")
    assert no_token.status_code == 403
    assert no_token.json()["error"]["code"] == "csrf_failed"
    forged = await owner_client.http.post(
        "/api/v1/invitations", headers={"X-CSRF-Token": "forged.token"}
    )
    assert forged.status_code == 403
    csrf = await owner_client.csrf()
    wrong_origin = await owner_client.http.post(
        "/api/v1/invitations", headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"}
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error"]["code"] == "csrf_origin_mismatch"
    ok = await owner_client.post("/api/v1/invitations")
    assert ok.status_code == 201

    # An anonymous CSRF token cannot be replayed inside an authenticated session.
    stranger: ApiClient = make_client()
    anon_token = await stranger.csrf()
    session = owner_client.http.cookies.get("twoofus_session") or ""
    mixed = replayer(make_client, twoofus_session=session, twoofus_csrf=anon_token)
    replay = await mixed.http.post("/api/v1/invitations", headers={"X-CSRF-Token": anon_token})
    assert replay.status_code == 403


async def test_logout_revokes_the_session(
    owner_client: ApiClient, ctx: AppContext, make_client: Any
) -> None:
    old_cookie = owner_client.http.cookies.get("twoofus_session") or ""
    response = await owner_client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert (await owner_client.get("/api/v1/me")).status_code == 401
    replay = await replayer(make_client, twoofus_session=old_cookie).get("/api/v1/me")
    assert replay.status_code == 401
    async with ctx.session_factory() as db:
        revoked = (
            await db.execute(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.revoked_at.is_not(None))
            )
        ).scalar_one()
    assert revoked == 1


async def test_login_issues_a_new_session_each_time(
    owner_client: ApiClient, make_client: Any
) -> None:
    first = owner_client.http.cookies.get("twoofus_session") or ""
    await owner_client.login("khaled", OWNER_PASSWORD)
    second = owner_client.http.cookies.get("twoofus_session")
    assert first != second
    replay = await replayer(make_client, twoofus_session=first).get("/api/v1/me")
    assert replay.status_code == 401  # previous session revoked (no fixation)


async def test_session_rotation_grace_and_idle_expiry(
    owner_client: ApiClient, clock: FakeClock, make_client: Any
) -> None:
    original = owner_client.http.cookies.get("twoofus_session") or ""
    clock.advance(hours=25)
    response = await owner_client.get("/api/v1/me")
    assert response.status_code == 200
    rotated = owner_client.http.cookies.get("twoofus_session")
    assert rotated
    assert rotated != original

    # A request already in flight with the old cookie still succeeds, without
    # rotating again (only one response may hand out the new token)...
    in_flight = replayer(make_client, twoofus_session=original)
    late = await in_flight.get("/api/v1/me")
    assert late.status_code == 200
    assert "twoofus_session" not in late.cookies
    # ...but only during the short grace period.
    clock.advance(seconds=ROTATION_GRACE.total_seconds() + 1)
    assert (await in_flight.get("/api/v1/me")).status_code == 401
    assert (await owner_client.get("/api/v1/me")).status_code == 200

    clock.advance(days=15)  # idle longer than SESSION_IDLE_DAYS
    assert (await owner_client.get("/api/v1/me")).status_code == 401


async def test_simultaneous_requests_rotate_the_token_once(
    owner_client: ApiClient, clock: FakeClock, make_client: Any
) -> None:
    original = owner_client.http.cookies.get("twoofus_session") or ""
    clock.advance(hours=25)
    first, second = (replayer(make_client, twoofus_session=original) for _ in range(2))
    responses = await asyncio.gather(first.get("/api/v1/me"), second.get("/api/v1/me"))
    assert [r.status_code for r in responses] == [200, 200]
    issued = [r.cookies["twoofus_session"] for r in responses if "twoofus_session" in r.cookies]
    assert len(issued) == 1
    winner = replayer(make_client, twoofus_session=issued[0])
    assert (await winner.get("/api/v1/me")).status_code == 200


async def test_rotation_race_has_a_single_winner(owner_client: ApiClient, ctx: AppContext) -> None:
    # Two requests that loaded the session before either rotated it: the
    # conditional UPDATE lets only the first one swap the token.
    presented = hash_token(owner_client.http.cookies.get("twoofus_session") or "")
    now = ctx.clock() + timedelta(hours=25)
    async with ctx.session_factory() as db_a, ctx.session_factory() as db_b:
        row_a = (await db_a.execute(select(AuthSession))).scalar_one()
        row_b = (await db_b.execute(select(AuthSession))).scalar_one()
        token_a = await sessions._rotate(db_a, row_a, presented, now)
        await db_a.commit()
        token_b = await sessions._rotate(db_b, row_b, presented, now)
        await db_b.commit()
    assert token_a is not None
    assert token_b is None
    async with ctx.session_factory() as db:
        stored = (await db.execute(select(AuthSession))).scalar_one()
    assert stored.token_hash == hash_token(token_a)
    assert stored.previous_token_hash == presented


async def test_absolute_expiry(owner_client: ApiClient, clock: FakeClock) -> None:
    for _ in range(4):
        clock.advance(days=8)
        await owner_client.get("/api/v1/me")
    assert (await owner_client.get("/api/v1/me")).status_code == 401  # > 30 days total


async def test_expired_session_reports_session_expired_on_writes(
    owner_client: ApiClient, clock: FakeClock
) -> None:
    clock.advance(days=31)
    response = await owner_client.post("/api/v1/invitations")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


async def test_validation_errors_do_not_echo_input(make_client: Any) -> None:
    client: ApiClient = make_client()
    response = await client.post(
        "/api/v1/auth/login", json={"username": "khaled", "password": "", "extra": "SECRETVALUE"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "SECRETVALUE" not in response.text


# ----- owner bootstrap ------------------------------------------------------------------


async def test_setup_status_and_no_web_bootstrap(make_client: Any) -> None:
    client: ApiClient = make_client()
    assert (await client.get("/api/v1/setup/status")).json() == {"owner_exists": True}
    # Owners are created on the server (CLI) only; there is no web endpoint for it.
    response = await client.post(
        "/api/v1/setup/owner",
        json={"username": "eve", "display_name": "Eve", "password": "long-password-1"},
    )
    assert response.status_code == 404


async def test_csrf_token_is_kept_while_valid(make_client: Any) -> None:
    # Re-reading the session must not churn the token (writes in flight would break).
    client: ApiClient = make_client()
    first = (await client.get("/api/v1/auth/session")).json()["csrf_token"]
    assert (await client.get("/api/v1/auth/session")).json()["csrf_token"] == first
    assert (await client.get("/api/v1/auth/csrf")).json()["csrf_token"] == first

    signed_in = (await client.login("khaled", OWNER_PASSWORD)).json()["csrf_token"]
    assert signed_in != first  # new binding after login
    assert (await client.get("/api/v1/auth/session")).json()["csrf_token"] == signed_in
    assert client.http.cookies.get("twoofus_csrf") == signed_in

    # A token planted for another binding is replaced, never reused.
    client.http.cookies.set("twoofus_csrf", first)
    replaced = (await client.get("/api/v1/auth/session")).json()["csrf_token"]
    assert replaced not in {first, signed_in}
