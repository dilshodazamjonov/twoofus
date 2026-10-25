"""Connecting the signed-in member's own music service."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import Auth, Ctx, Db, OptionalAuth, client_ip
from app.core.ratelimit import Limit
from app.models import ProviderConnection, ProviderName
from app.schemas.providers import (
    AuthorizeOut,
    ConnectionOut,
    DeviceFlowOut,
    PendingAuthorizationOut,
    ProviderAvailabilityOut,
    ProvidersOut,
)
from app.services import provider_auth
from app.services.provider_auth import DeviceFlowView

router = APIRouter(prefix="/providers", tags=["providers"])

CALLBACK_PER_IP = Limit(attempts=30, window_seconds=15 * 60)
SPOTIFY_REFRESH_TOKEN_LIFETIME = timedelta(days=182)  # "6 months" per Spotify docs
# Where the browser lands after the Spotify callback (the frontend owns the UI).
POST_CONNECT_PATH = "/"

LABELS = {
    ProviderName.SPOTIFY: ("Spotify", True),
    ProviderName.YANDEX: ("Yandex Music", False),
    ProviderName.DEMO: ("Demo (fake songs)", False),
}


def connection_out(conn: ProviderConnection) -> ConnectionOut:
    reauthorize_by = (
        conn.authorized_at + SPOTIFY_REFRESH_TOKEN_LIFETIME
        if conn.provider == ProviderName.SPOTIFY.value
        else conn.token_expires_at
    )
    return ConnectionOut(
        provider=conn.provider,  # type: ignore[arg-type]  # constrained by a CHECK
        status=conn.status,  # type: ignore[arg-type]
        authorized_at=conn.authorized_at,
        reauthorize_by=reauthorize_by,
        last_fetch_at=conn.last_fetch_at,
        last_success_at=conn.last_success_at,
        last_error_code=conn.last_error_code,
        last_error_at=conn.last_error_at,
        backoff_until=conn.backoff_until,
    )


def device_flow_out(view: DeviceFlowView) -> DeviceFlowOut:
    return DeviceFlowOut(
        status=view.status,  # type: ignore[arg-type]
        user_code=view.user_code,
        verification_url=view.verification_url,
        expires_at=view.expires_at,
        poll_interval_seconds=view.poll_interval_seconds,
        error_code=view.error_code,
    )


@router.get("", response_model=ProvidersOut, summary="Available services and my connection")
async def providers(ctx: Ctx, db: Db, auth: Auth) -> ProvidersOut:
    available = ctx.providers.available()
    conn = await provider_auth.get_connection(db, auth.user.id)
    flow = await provider_auth.pending_flow(db, ctx, auth.user.id)
    return ProvidersOut(
        providers=[
            ProviderAvailabilityOut(
                name=name.value,
                label=label,
                available=name in available,
                experimental=name is ProviderName.YANDEX,
                official_api=official,
            )
            for name, (label, official) in LABELS.items()
            if name is not ProviderName.DEMO or ctx.settings.demo_mode
        ],
        connection=connection_out(conn) if conn else None,
        pending_authorization=(
            PendingAuthorizationOut(
                provider=flow.provider,  # type: ignore[arg-type]
                kind=flow.kind,  # type: ignore[arg-type]
                expires_at=flow.expires_at,
            )
            if flow
            else None
        ),
    )


@router.delete("/connection", status_code=204, summary="Disconnect and delete stored credentials")
async def disconnect(ctx: Ctx, db: Db, auth: Auth) -> Response:
    await provider_auth.disconnect(db, ctx, auth.user.id)
    return Response(status_code=204)


# ----- Spotify ------------------------------------------------------------------


@router.post(
    "/spotify/authorize",
    response_model=AuthorizeOut,
    summary="Start Spotify authorisation (Authorization Code + PKCE)",
)
async def spotify_authorize(ctx: Ctx, db: Db, auth: Auth) -> AuthorizeOut:
    url = await provider_auth.start_spotify(
        db, ctx, user_id=auth.user.id, session_id=auth.session.id
    )
    return AuthorizeOut(authorization_url=url)


@router.get(
    "/spotify/callback",
    summary="Spotify redirects here; validates state + session, then redirects to the app",
    response_class=RedirectResponse,
    status_code=303,
)
async def spotify_callback(
    request: Request,
    ctx: Ctx,
    db: Db,
    auth: OptionalAuth,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    ctx.rate_limiter.check(f"callback:ip:{client_ip(request)}", CALLBACK_PER_IP)
    result = await provider_auth.complete_spotify(
        db,
        ctx,
        state=state,
        code=code[:2048] if code else None,
        error=error[:64] if error else None,
        user_id=auth.user.id if auth else None,
        session_id=auth.session.id if auth else None,
    )
    query = urlencode({"connect": "spotify", "result": result.value})
    return RedirectResponse(f"{POST_CONNECT_PATH}?{query}", status_code=303)


# ----- Yandex (experimental) ---------------------------------------------------------


@router.post(
    "/yandex/device-authorization",
    response_model=DeviceFlowOut,
    status_code=201,
    summary="Start Yandex device authorisation (user approves on Yandex's own page)",
)
async def yandex_start(ctx: Ctx, db: Db, auth: Auth) -> DeviceFlowOut:
    view = await provider_auth.start_yandex(
        db, ctx, user_id=auth.user.id, session_id=auth.session.id
    )
    return device_flow_out(view)


@router.post(
    "/yandex/device-authorization/poll",
    response_model=DeviceFlowOut,
    summary="Advance the device flow (at most one upstream check per interval)",
)
async def yandex_poll(ctx: Ctx, db: Db, auth: Auth) -> DeviceFlowOut:
    view = await provider_auth.poll_yandex(
        db, ctx, user_id=auth.user.id, session_id=auth.session.id
    )
    return device_flow_out(view)


@router.delete(
    "/yandex/device-authorization", status_code=204, summary="Cancel device authorisation"
)
async def yandex_cancel(ctx: Ctx, db: Db, auth: Auth) -> Response:
    await provider_auth.cancel_yandex(db, ctx, user_id=auth.user.id, session_id=auth.session.id)
    return Response(status_code=204)


# ----- Demo ----------------------------------------------------------------------


@router.post(
    "/demo/connect",
    response_model=ConnectionOut,
    summary="Use the DEMO provider (only when DEMO_MODE=true)",
)
async def demo_connect(ctx: Ctx, db: Db, auth: Auth) -> ConnectionOut:
    conn = await provider_auth.connect_demo(db, ctx, auth.user.id)
    return connection_out(conn)
