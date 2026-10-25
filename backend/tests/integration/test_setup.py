"""First run: no owner exists yet in this module; the CLI creates one."""

from __future__ import annotations

import io
from typing import Any

import pytest

from app.cli import bootstrap_owner
from tests.conftest import ApiClient, make_settings

PAYLOAD = {"username": "khaled", "display_name": "Khaled", "password": "long-password-1"}


async def test_setup_status_before_and_after_the_owner_exists(make_client: Any, ctx: Any) -> None:
    from app.services import accounts

    client: ApiClient = make_client()
    assert (await client.get("/api/v1/setup/status")).json() == {"owner_exists": False}
    async with ctx.session_factory() as db:
        await accounts.create_owner(db, ctx, **PAYLOAD)
    assert (await client.get("/api/v1/setup/status")).json() == {"owner_exists": True}


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
    database_url: str, make_client: Any, monkeypatch: pytest.MonkeyPatch, app: Any
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.cli import reset_password
    from app.services import accounts

    ctx = app.state.ctx
    async with ctx.session_factory() as db:
        await accounts.create_owner(db, ctx, **PAYLOAD)
    client: ApiClient = make_client()
    assert (await client.login("khaled", PAYLOAD["password"])).status_code == 200
    assert (await client.get("/api/v1/me")).status_code == 200

    settings = make_settings(database_url)
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
