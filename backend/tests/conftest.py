"""Test harness.

* Every test gets a freshly migrated database (Alembic, not create_all), so the
  migrations themselves are exercised. SQLite by default; set
  TWOOFUS_TEST_DATABASE_URL to a *disposable* PostgreSQL database to run the
  whole suite there instead (its public schema is dropped per test).
* No real credentials or network: Spotify is mocked with respx, Yandex with a
  fake gateway, time with a controllable clock.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from fastapi import FastAPI
from sqlalchemy import create_engine, text

from app.context import AppContext
from app.core.config import BACKEND_DIR, Settings
from app.core.crypto import generate_key
from app.main import close_context, create_app
from app.models import User
from app.providers.base import ProviderError
from app.providers.yandex import (
    DeviceCode,
    YandexHistoryTrack,
    YandexToken,
    YandexTrackMeta,
    YnisonPlayable,
    YnisonSnapshot,
)
from app.services import accounts

APP_ORIGIN = "http://127.0.0.1:3000"
SPOTIFY_REDIRECT = f"{APP_ORIGIN}/api/v1/providers/spotify/callback"
OWNER_PASSWORD = "owner-password-123"
PARTNER_PASSWORD = "partner-password-456"
PG_URL = os.environ.get("TWOOFUS_TEST_DATABASE_URL", "")


# ----- database ---------------------------------------------------------------------


def _alembic_upgrade(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logger"] = False
    # env.py uses asyncio.run(); keep it off pytest-asyncio's event loop thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(command.upgrade, cfg, "head").result()


@pytest.fixture(scope="session")
def sqlite_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("template") / "template.db"
    _alembic_upgrade(f"sqlite+aiosqlite:///{path}")
    with closing(sqlite3.connect(path)) as conn:  # fold the WAL into the main file
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


@pytest.fixture
def database_url(tmp_path: Path, sqlite_template: Path) -> Iterator[str]:
    if PG_URL:
        sync_url = PG_URL.replace("+asyncpg", "+psycopg")
        engine = create_engine(sync_url)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()
        _alembic_upgrade(PG_URL)
        yield PG_URL
        return
    path = tmp_path / "test.db"
    shutil.copyfile(sqlite_template, path)
    yield f"sqlite+aiosqlite:///{path}"


# ----- time, settings, fakes ---------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "public_app_url": APP_ORIGIN,
        "database_url": database_url,
        "secret_key": "test-secret-key-" + "x" * 40,
        "token_encryption_keys": generate_key(),
        "demo_mode": True,
        "spotify_client_id": "test-client-id",
        "spotify_redirect_uri": SPOTIFY_REDIRECT,
        "yandex_enabled": True,
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@dataclass
class FakeYandexGateway:
    device_code: DeviceCode = field(
        default_factory=lambda: DeviceCode(
            device_code="device-code-SECRET-123",
            user_code="ABCD-1234",
            verification_url="https://ya.ru/device",
            expires_in=300,
            interval=5,
        )
    )
    poll_results: list[YandexToken | Exception | None] = field(default_factory=list)
    snapshot: YnisonSnapshot | Exception = field(
        default_factory=lambda: YnisonSnapshot(
            has_active_device=False, paused=True, progress_ms=None, duration_ms=None, playable=None
        )
    )
    tracks: dict[str, YandexTrackMeta | Exception | None] = field(default_factory=dict)
    history: tuple[YandexHistoryTrack, ...] | Exception = ()
    calls: Counter[str] = field(default_factory=Counter)
    tokens_seen: list[str] = field(default_factory=list)
    device_names: list[str] = field(default_factory=list)
    device_ids: list[str] = field(default_factory=list)
    revoke_result: bool | Exception = True
    revoked: list[str] = field(default_factory=list)

    async def request_device_code(self, *, device_name: str, device_id: str) -> DeviceCode:
        self.calls["device_code"] += 1
        self.device_names.append(device_name)
        self.device_ids.append(device_id)
        return self.device_code

    async def revoke_token(self, access_token: str) -> bool:
        self.calls["revoke"] += 1
        self.revoked.append(access_token)
        if isinstance(self.revoke_result, Exception):
            raise self.revoke_result
        return self.revoke_result

    async def poll_device_token(self, device_code: str) -> YandexToken | None:
        self.calls["poll"] += 1
        assert device_code == self.device_code.device_code
        result = self.poll_results.pop(0) if self.poll_results else None
        if isinstance(result, Exception):
            raise result
        return result

    async def fetch_player_state(
        self, access_token: str, *, device_id: str, device_title: str
    ) -> YnisonSnapshot:
        self.calls["state"] += 1
        self.tokens_seen.append(access_token)
        assert len(device_id) == 12
        assert "read-only" in device_title
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot

    async def fetch_track(self, access_token: str, track_id: str) -> YandexTrackMeta | None:
        self.calls["track"] += 1
        result = self.tracks.get(track_id)
        if isinstance(result, Exception):
            raise result
        return result

    async def fetch_history(
        self, access_token: str, *, limit: int
    ) -> tuple[YandexHistoryTrack, ...]:
        self.calls["history"] += 1
        self.tokens_seen.append(access_token)
        if isinstance(self.history, Exception):
            raise self.history
        return self.history[:limit]


def yandex_playing(
    track_id: str = "10994777", album_id: str = "1193829", paused: bool = False
) -> YnisonSnapshot:
    return YnisonSnapshot(
        has_active_device=True,
        paused=paused,
        progress_ms=42_000,
        duration_ms=200_000,
        playable=YnisonPlayable(
            playable_id=track_id,
            album_id=album_id,
            kind="track",
            title="Ynison Title",
            cover_url="avatars.yandex.net/get-music-content/123/abc/%%",
        ),
    )


@pytest.fixture
def yandex_gateway() -> FakeYandexGateway:
    return FakeYandexGateway()


FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


# ----- app & clients ----------------------------------------------------------------


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {}


@pytest.fixture
async def app(
    database_url: str,
    clock: FakeClock,
    yandex_gateway: FakeYandexGateway,
    settings_overrides: dict[str, Any],
) -> AsyncIterator[FastAPI]:
    application = create_app(
        make_settings(database_url, **settings_overrides),
        clock=clock,
        yandex_gateway=yandex_gateway,
        password_hasher=FAST_HASHER,
        run_background_tasks=False,
    )
    yield application
    await close_context(application.state.ctx)


@pytest.fixture
def ctx(app: FastAPI) -> AppContext:
    context: AppContext = app.state.ctx
    return context


class ApiClient:
    """One browser: its own cookie jar, Origin header and CSRF handling."""

    def __init__(self, app: FastAPI, origin: str = APP_ORIGIN) -> None:
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=APP_ORIGIN,
            headers={"Origin": origin},
        )

    async def csrf(self) -> str:
        token = self.http.cookies.get("twoofus_csrf")
        if token is None:
            response = await self.http.get("/api/v1/auth/csrf")
            token = response.json()["csrf_token"]
        return token

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            headers.setdefault("X-CSRF-Token", await self.csrf())
        return await self.http.request(method, url, headers=headers, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", url, **kwargs)

    async def login(self, username: str, password: str) -> httpx.Response:
        return await self.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )

    async def aclose(self) -> None:
        await self.http.aclose()


@pytest.fixture
async def make_client(app: FastAPI) -> AsyncIterator[Any]:
    clients: list[ApiClient] = []

    def factory(origin: str = APP_ORIGIN) -> ApiClient:
        client = ApiClient(app, origin)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
async def owner(ctx: AppContext) -> User:
    async with ctx.session_factory() as db:
        return await accounts.create_owner(
            db, ctx, username="khaled", display_name="Khaled", password=OWNER_PASSWORD
        )


@pytest.fixture
async def owner_client(owner: User, make_client: Any) -> ApiClient:
    client: ApiClient = make_client()
    response = await client.login("khaled", OWNER_PASSWORD)
    assert response.status_code == 200, response.text
    return client


async def invite_partner(owner_client: ApiClient, partner_client: ApiClient) -> httpx.Response:
    created = await owner_client.post("/api/v1/invitations")
    assert created.status_code == 201, created.text
    return await partner_client.post(
        "/api/v1/invitations/accept",
        json={
            "token": created.json()["token"],
            "username": "amira",
            "display_name": "Amira",
            "password": PARTNER_PASSWORD,
        },
    )


@pytest.fixture
async def partner_client(owner_client: ApiClient, make_client: Any) -> ApiClient:
    client: ApiClient = make_client()
    response = await invite_partner(owner_client, client)
    assert response.status_code == 201, response.text
    return client


async def enable_sharing(client: ApiClient) -> None:
    config = (await client.get("/api/v1/config")).json()
    response = await client.put(
        "/api/v1/me/sharing",
        json={
            "share_now_playing": True,
            "acknowledged_notice_version": config["sharing_notice_version"],
        },
    )
    assert response.status_code == 200, response.text


__all__ = [
    "APP_ORIGIN",
    "OWNER_PASSWORD",
    "PARTNER_PASSWORD",
    "SPOTIFY_REDIRECT",
    "ApiClient",
    "FakeClock",
    "FakeYandexGateway",
    "ProviderError",
    "enable_sharing",
    "invite_partner",
    "make_settings",
    "yandex_playing",
]
