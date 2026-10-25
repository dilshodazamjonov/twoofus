"""Print the OpenAPI document; the frontend generates its TypeScript types from it.

    uv run python -m app.cli.openapi > openapi.json

The app is built with throwaway settings (random secrets, an in-memory
database URL that is never opened, the Demo provider and a placeholder Spotify
client id so every route is documented). It never reads backend/.env and
makes no network or database connection.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from typing import Any

from pydantic import SecretStr

from app.core.config import SPOTIFY_CALLBACK_PATH, Settings
from app.core.crypto import generate_key
from app.main import close_context, create_app

_ORIGIN = "http://127.0.0.1:3000"


def openapi_document() -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        environment="development",
        public_app_url=_ORIGIN,
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key=SecretStr(secrets.token_urlsafe(48)),
        token_encryption_keys=SecretStr(generate_key()),
        demo_mode=True,
        spotify_client_id="openapi-placeholder",
        spotify_redirect_uri=_ORIGIN + SPOTIFY_CALLBACK_PATH,
        yandex_enabled=True,
    )
    app = create_app(settings, run_background_tasks=False)
    try:
        return app.openapi()
    finally:
        asyncio.run(close_context(app.state.ctx))


def main() -> int:
    json.dump(openapi_document(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
