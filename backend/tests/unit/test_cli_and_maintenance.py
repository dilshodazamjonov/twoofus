from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from app.cli import keys
from app.context import AppContext
from app.core.config import Settings
from app.models import AuthSession, Invitation, ProviderAuthFlow
from app.services.maintenance import purge_expired
from tests.conftest import FakeClock


def test_keys_print(capsys: pytest.CaptureFixture[str]) -> None:
    assert keys.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("SECRET_KEY=")
    assert "TOKEN_ENCRYPTION_KEYS=" in out


def test_keys_init_env_creates_a_valid_env_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = Path(keys.BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    (tmp_path / ".env.example").write_text(example, encoding="utf-8")
    monkeypatch.setattr(keys, "BACKEND_DIR", tmp_path)
    assert keys.main(["--init-env"]) == 0
    env = tmp_path / ".env"
    assert env.stat().st_mode & 0o777 == 0o600
    settings = Settings(_env_file=env)  # type: ignore[call-arg]
    assert len(settings.encryption_keys()) == 1
    first = env.read_text(encoding="utf-8")
    assert keys.main(["--init-env"]) == 0  # never overwrites
    assert env.read_text(encoding="utf-8") == first


async def test_purge_expired_rows(
    ctx: AppContext, clock: FakeClock, owner_client: Any, make_client: Any
) -> None:
    await owner_client.post("/api/v1/invitations")
    await owner_client.post("/api/v1/providers/yandex/device-authorization")
    await owner_client.post("/api/v1/auth/logout")

    async def counts() -> list[int]:
        result = []
        async with ctx.session_factory() as db:
            for model in (AuthSession, Invitation, ProviderAuthFlow):
                result.append(
                    (await db.execute(select(func.count()).select_from(model))).scalar_one()
                )
        return result

    assert await counts() == [1, 1, 1]
    async with ctx.session_factory() as db:
        await purge_expired(db, clock)
    assert await counts() == [1, 1, 1]  # nothing old enough yet

    clock.advance(days=40)
    async with ctx.session_factory() as db:
        await purge_expired(db, clock)
    assert await counts() == [0, 0, 0]
