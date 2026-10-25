"""Health, readiness and the public capabilities/config endpoint (no secrets)."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.api.deps import Ctx, Db
from app.core.config import SHARING_NOTICE_VERSION
from app.migrations_info import expected_head
from app.schemas.providers import ConfigOut, ConfigProviderOut, HealthOut, ReadyOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])

API_VERSION = "1"


@router.get("/health", response_model=HealthOut, summary="Liveness probe")
async def health() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/ready", response_model=ReadyOut, summary="Readiness: database + migrations")
async def ready(db: Db, response: Response) -> ReadyOut:
    database: Literal["ok", "error"] = "ok"
    migrations: Literal["ok", "pending", "unknown"] = "unknown"
    try:
        await db.execute(text("SELECT 1"))
        current = (
            await db.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        head = expected_head()
        if head is not None:
            migrations = "ok" if current == head else "pending"
    except Exception as exc:  # report, don't crash the probe
        logger.warning("readiness check failed: %s", type(exc).__name__)
        database = "error"
    is_ready = database == "ok" and migrations == "ok"
    if not is_ready:
        response.status_code = 503
    return ReadyOut(
        status="ready" if is_ready else "not_ready", database=database, migrations=migrations
    )


@router.get("/config", response_model=ConfigOut, summary="Public capabilities (never secrets)")
async def config(ctx: Ctx) -> ConfigOut:
    available = ctx.providers.available()
    return ConfigOut(
        app_name=ctx.settings.app_name,
        environment=ctx.settings.environment,
        demo_mode=ctx.settings.demo_mode,
        providers={
            "spotify": ConfigProviderOut(available="spotify" in available, experimental=False),
            "yandex": ConfigProviderOut(available="yandex" in available, experimental=True),
            "demo": ConfigProviderOut(available="demo" in available, experimental=False),
        },
        now_playing_ttl_seconds=ctx.settings.now_playing_ttl_seconds,
        sharing_notice_version=SHARING_NOTICE_VERSION,
        api_version=API_VERSION,
    )
