"""Token-gated web bootstrap (no owner exists yet in this module)."""

from __future__ import annotations

import io
from typing import Any

import pytest

from app.cli import bootstrap_owner
from tests.conftest import ApiClient, make_settings

TOKEN = "B" * 48
PAYLOAD = {"username": "khaled", "display_name": "Khaled", "password": "long-password-1"}


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    return {"bootstrap_token": TOKEN}


async def test_web_bootstrap_with_token(make_client: Any) -> None:
    client: ApiClient = make_client()
    assert (await client.get("/api/v1/setup/status")).json() == {
        "owner_exists": False,
        "web_bootstrap_enabled": True,
    }
    bad = await client.post("/api/v1/setup/owner", json={"bootstrap_token": "C" * 48, **PAYLOAD})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "invalid_bootstrap_token"

    good = await client.post("/api/v1/setup/owner", json={"bootstrap_token": TOKEN, **PAYLOAD})
    assert good.status_code == 201
    assert good.json()["user"]["role"] == "owner"
    assert (await client.get("/api/v1/me")).status_code == 200  # signed in right away

    other: ApiClient = make_client()
    again = await other.post(
        "/api/v1/setup/owner", json={"bootstrap_token": TOKEN, **PAYLOAD, "username": "eve"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_bootstrapped"
    assert (await client.get("/api/v1/setup/status")).json()["web_bootstrap_enabled"] is False


async def test_web_bootstrap_is_rate_limited(make_client: Any) -> None:
    client: ApiClient = make_client()
    for _ in range(5):
        await client.post("/api/v1/setup/owner", json={"bootstrap_token": "C" * 48, **PAYLOAD})
    limited = await client.post("/api/v1/setup/owner", json={"bootstrap_token": TOKEN, **PAYLOAD})
    assert limited.status_code == 429


def test_cli_bootstrap_owner(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(database_url)
    monkeypatch.setattr(bootstrap_owner, "get_settings", lambda: settings)
    monkeypatch.setattr("sys.stdin", io.StringIO("cli-password-123\n"))
    code = bootstrap_owner.main(
        ["--username", "Khaled", "--display-name", "Khaled", "--password-stdin"]
    )
    assert code == 0
    assert "Owner 'khaled' created" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("cli-password-123\n"))
    again = bootstrap_owner.main(["--username", "other", "--display-name", "O", "--password-stdin"])
    assert again == 1
    assert "already has an owner" in capsys.readouterr().err


async def test_cli_reset_password_signs_out_everywhere(
    database_url: str, make_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.cli import reset_password

    client: ApiClient = make_client()
    await client.post("/api/v1/setup/owner", json={"bootstrap_token": TOKEN, **PAYLOAD})
    assert (await client.get("/api/v1/me")).status_code == 200

    settings = make_settings(database_url, bootstrap_token=TOKEN)
    monkeypatch.setattr(reset_password, "get_settings", lambda: settings)

    def run(argv: list[str], stdin: str) -> int:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        return reset_password.main(argv)

    # The CLI uses asyncio.run(); keep it off the test's running event loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert (
            pool.submit(
                run, ["--username", "nobody", "--password-stdin"], "brand-new-pass-1\n"
            ).result()
            == 1
        )
        assert (
            pool.submit(run, ["--username", "khaled", "--password-stdin"], "short\n").result() == 2
        )
        assert (
            pool.submit(
                run, ["--username", "KHALED", "--password-stdin"], "brand-new-pass-1\n"
            ).result()
            == 0
        )

    assert (await client.get("/api/v1/me")).status_code == 401  # signed out everywhere
    fresh: ApiClient = make_client()
    assert (await fresh.login("khaled", PAYLOAD["password"])).status_code == 401
    assert (await fresh.login("khaled", "brand-new-pass-1")).status_code == 200
