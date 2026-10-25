"""Connecting and disconnecting a member's music service.

Credentials are encrypted before they touch the database, bound (via AEAD
associated data) to the owning user, provider and field. Pending
authorisations are bound to the app session that started them.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.crypto import DecryptionError
from app.core.errors import Conflict, NotFound, ServiceUnavailable
from app.core.security import hash_token, new_token
from app.models import (
    AuthFlowKind,
    AuthFlowStatus,
    ConnectionStatus,
    ProviderAuthFlow,
    ProviderConnection,
    ProviderName,
)
from app.providers.base import ProviderError, TokenSet
from app.providers.demo import DemoProvider, DemoScenario
from app.providers.spotify import code_challenge_s256, new_code_verifier
from app.providers.yandex import DeviceFlowError, DeviceFlowPending
from app.services.credentials import flow_context, token_context

logger = logging.getLogger(__name__)

SPOTIFY_FLOW_TTL = timedelta(minutes=10)
_YANDEX_UNREACHABLE_BACKOFF = 10
_REVOKE_TIMEOUT_SECONDS = 5.0


class ProviderUnavailable(ServiceUnavailable):
    code = "provider_not_available"
    message = "This music service is not enabled on this server."


class Revocation(StrEnum):
    """What happened to the grant at the provider when we dropped our copy."""

    REVOKED = "revoked"  # the provider confirmed the token is invalid now
    FAILED = "failed"  # we asked, it did not confirm (our copy is deleted anyway)
    NOT_SUPPORTED = "not_supported"  # Spotify has no revocation API: spotify.com/account/apps
    NOT_APPLICABLE = "not_applicable"  # demo, or nothing usable was stored


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    provider: str | None
    revocation: Revocation | None


@dataclass(frozen=True, slots=True)
class StoredGrant:
    """A provider and its decrypted access token, kept just long enough to revoke it."""

    provider: str
    access_token: str | None


class CallbackResult(StrEnum):
    CONNECTED = "connected"
    DENIED = "access_denied"
    INVALID_STATE = "invalid_state"
    SESSION_MISMATCH = "session_mismatch"
    FAILED = "failed"


# ----- connection storage ------------------------------------------------------


async def get_connection(db: AsyncSession, user_id: uuid.UUID) -> ProviderConnection | None:
    return (
        await db.execute(select(ProviderConnection).where(ProviderConnection.user_id == user_id))
    ).scalar_one_or_none()


def stored_grant(ctx: AppContext, conn: ProviderConnection) -> StoredGrant:
    access: str | None = None
    if conn.access_token_enc is not None:
        try:
            access = ctx.cipher.decrypt(
                conn.access_token_enc, context=token_context(conn.user_id, conn.provider, "access")
            )
        except DecryptionError:
            access = None
    return StoredGrant(provider=conn.provider, access_token=access)


async def revoke_at_provider(ctx: AppContext, grant: StoredGrant | None) -> Revocation | None:
    """Best effort, called after our copy is already deleted; never raises.

    Yandex ID revokes tokens issued for a device (ours are); Spotify's Web API
    has no revocation endpoint, so the person removes the app at
    spotify.com/account/apps (the UI says so).
    """
    if grant is None:
        return None
    if grant.provider == ProviderName.SPOTIFY.value:
        return Revocation.NOT_SUPPORTED
    if grant.provider != ProviderName.YANDEX.value or not grant.access_token:
        return Revocation.NOT_APPLICABLE
    yandex = ctx.providers.yandex
    if yandex is None:
        return Revocation.FAILED
    try:
        async with asyncio.timeout(_REVOKE_TIMEOUT_SECONDS):
            confirmed = await yandex.revoke(grant.access_token)
    except Exception as exc:  # best effort: never let this break a disconnect
        logger.warning("Yandex revocation call failed: %s", type(exc).__name__)
        return Revocation.FAILED
    if not confirmed:
        logger.warning("Yandex did not confirm the token revocation")
    return Revocation.REVOKED if confirmed else Revocation.FAILED


async def store_connection(
    db: AsyncSession,
    ctx: AppContext,
    *,
    user_id: uuid.UUID,
    provider: ProviderName,
    tokens: TokenSet | None,
) -> tuple[ProviderConnection, StoredGrant | None]:
    """Create or replace the user's (single) provider connection.

    Returns the connection and, when an older grant was replaced, that grant so
    the caller can revoke it after committing (only if it differs from the new
    token: Yandex may hand out the same token again for the same device).
    """
    now = ctx.clock()
    conn = await get_connection(db, user_id)
    replaced: StoredGrant | None = None
    if conn is None:
        conn = ProviderConnection(user_id=user_id, created_at=now, token_version=0)
        db.add(conn)
    else:
        old = stored_grant(ctx, conn)
        new_access = tokens.access_token if tokens else None
        if old.access_token and old.access_token != new_access:
            replaced = old
    conn.provider = provider.value
    conn.status = ConnectionStatus.ACTIVE.value
    conn.access_token_enc = (
        ctx.cipher.encrypt(tokens.access_token, context=token_context(user_id, provider, "access"))
        if tokens
        else None
    )
    conn.refresh_token_enc = (
        ctx.cipher.encrypt(
            tokens.refresh_token, context=token_context(user_id, provider, "refresh")
        )
        if tokens and tokens.refresh_token
        else None
    )
    conn.token_expires_at = tokens.expires_at if tokens else None
    conn.scopes = tokens.scopes if tokens else None
    conn.token_version = (conn.token_version or 0) + 1
    conn.authorized_at = now
    conn.last_fetch_at = conn.last_success_at = conn.last_error_at = None
    conn.last_error_code = None
    conn.consecutive_failures = 0
    conn.backoff_until = conn.reauth_required_at = None
    conn.updated_at = now
    await db.flush()
    ctx.now_playing.evict(conn.id)
    return conn, replaced


async def disconnect(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> DisconnectResult:
    """Delete stored credentials, cancel pending authorisations, then ask the
    provider to revoke the grant where it supports that (Yandex)."""
    conn = await get_connection(db, user_id)
    await _cancel_pending_flows(db, ctx, user_id)
    if conn is None:
        await db.commit()
        return DisconnectResult(provider=None, revocation=None)
    grant = stored_grant(ctx, conn)
    ctx.now_playing.evict(conn.id)
    await db.execute(delete(ProviderConnection).where(ProviderConnection.id == conn.id))
    await db.commit()
    return DisconnectResult(
        provider=grant.provider, revocation=await revoke_at_provider(ctx, grant)
    )


async def connect_demo(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> ProviderConnection:
    demo = ctx.providers.demo
    if demo is None:
        raise ProviderUnavailable("Demo mode is disabled on this server.")
    await _cancel_pending_flows(db, ctx, user_id)
    conn, replaced = await store_connection(
        db, ctx, user_id=user_id, provider=ProviderName.DEMO, tokens=None
    )
    await db.commit()
    await revoke_at_provider(ctx, replaced)
    demo.set_scenario(str(conn.id), "live")  # a fresh connection starts on the timeline
    return conn


async def _demo_connection(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID
) -> tuple[DemoProvider, ProviderConnection]:
    demo = ctx.providers.demo
    if demo is None or not ctx.settings.demo_controls_enabled:
        raise NotFound  # development-only feature: invisible otherwise
    conn = await get_connection(db, user_id)
    if conn is None or conn.provider != ProviderName.DEMO.value:
        raise Conflict("Connect the Demo service first.", code="not_demo")
    return demo, conn


async def demo_scenario(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> DemoScenario:
    demo, conn = await _demo_connection(db, ctx, user_id)
    return demo.scenario(str(conn.id))


async def set_demo_scenario(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID, scenario: DemoScenario
) -> DemoScenario:
    """Pin the member's own demo connection to a scenario, effective on the next poll."""
    demo, conn = await _demo_connection(db, ctx, user_id)
    demo.set_scenario(str(conn.id), scenario)
    # Start from a clean slate so the new scenario shows up immediately.
    conn.status = ConnectionStatus.ACTIVE.value
    conn.backoff_until = conn.reauth_required_at = None
    conn.last_error_code = None
    conn.consecutive_failures = 0
    await db.commit()
    ctx.now_playing.invalidate(conn.id)
    return scenario


# ----- pending flows ------------------------------------------------------------


async def _cancel_pending_flows(db: AsyncSession, ctx: AppContext, user_id: uuid.UUID) -> None:
    await db.execute(
        update(ProviderAuthFlow)
        .where(
            ProviderAuthFlow.user_id == user_id,
            ProviderAuthFlow.status == AuthFlowStatus.PENDING.value,
        )
        .values(status=AuthFlowStatus.CANCELLED.value, secret_enc=None, completed_at=ctx.clock())
    )


def _finish(
    flow: ProviderAuthFlow, status: AuthFlowStatus, now: datetime, error: str | None = None
) -> None:
    flow.status = status.value
    flow.error_code = error
    flow.completed_at = now
    flow.secret_enc = None  # wipe the verifier / device code as soon as we are done


# ----- Spotify: Authorization Code + PKCE -----------------------------------


async def start_spotify(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> str:
    spotify = ctx.providers.spotify
    if spotify is None:
        raise ProviderUnavailable("Spotify is not configured on this server.")
    await _cancel_pending_flows(db, ctx, user_id)
    now = ctx.clock()
    verifier = new_code_verifier()
    state = new_token()
    flow = ProviderAuthFlow(
        id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        provider=ProviderName.SPOTIFY.value,
        kind=AuthFlowKind.OAUTH_PKCE.value,
        status=AuthFlowStatus.PENDING.value,
        state_hash=hash_token(state),
        created_at=now,
        expires_at=now + SPOTIFY_FLOW_TTL,
    )
    flow.secret_enc = ctx.cipher.encrypt(verifier, context=flow_context(flow.id, "code_verifier"))
    db.add(flow)
    await db.commit()
    return spotify.authorize_url(state=state, code_challenge=code_challenge_s256(verifier))


async def complete_spotify(
    db: AsyncSession,
    ctx: AppContext,
    *,
    state: str | None,
    code: str | None,
    error: str | None,
    user_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
) -> CallbackResult:
    now = ctx.clock()
    if not state or len(state) > 256:
        return CallbackResult.INVALID_STATE
    flow = (
        await db.execute(
            select(ProviderAuthFlow).where(
                ProviderAuthFlow.state_hash == hash_token(state),
                ProviderAuthFlow.provider == ProviderName.SPOTIFY.value,
                ProviderAuthFlow.status == AuthFlowStatus.PENDING.value,
            )
        )
    ).scalar_one_or_none()
    if flow is None:
        return CallbackResult.INVALID_STATE
    if flow.expires_at <= now:
        _finish(flow, AuthFlowStatus.EXPIRED, now, "expired")
        await db.commit()
        return CallbackResult.INVALID_STATE
    if session_id is None or flow.session_id != session_id or flow.user_id != user_id:
        # The callback arrived in a different (or no) app session: refuse, so a
        # victim cannot be tricked into linking an attacker's Spotify account.
        _finish(flow, AuthFlowStatus.FAILED, now, "session_mismatch")
        await db.commit()
        return CallbackResult.SESSION_MISMATCH
    if error or not code:
        _finish(
            flow,
            AuthFlowStatus.FAILED,
            now,
            "access_denied" if error == "access_denied" else "failed",
        )
        await db.commit()
        return CallbackResult.DENIED if error == "access_denied" else CallbackResult.FAILED

    spotify = ctx.providers.spotify
    if spotify is None or flow.secret_enc is None:
        _finish(flow, AuthFlowStatus.FAILED, now, "provider_not_configured")
        await db.commit()
        return CallbackResult.FAILED
    try:
        verifier = ctx.cipher.decrypt(
            flow.secret_enc, context=flow_context(flow.id, "code_verifier")
        )
        tokens = await spotify.exchange_code(code, verifier)
    except (DecryptionError, ProviderError) as exc:
        code_name = exc.code if isinstance(exc, ProviderError) else "decryption_failed"
        logger.warning("Spotify code exchange failed: %s", code_name)
        _finish(flow, AuthFlowStatus.FAILED, ctx.clock(), code_name)
        await db.commit()
        return CallbackResult.FAILED

    _, replaced = await store_connection(
        db, ctx, user_id=flow.user_id, provider=ProviderName.SPOTIFY, tokens=tokens
    )
    _finish(flow, AuthFlowStatus.COMPLETED, ctx.clock())
    await db.commit()
    await revoke_at_provider(ctx, replaced)
    return CallbackResult.CONNECTED


# ----- Yandex: OAuth device flow (polled by the frontend) --------------------


@dataclass(frozen=True, slots=True)
class DeviceFlowView:
    status: str
    user_code: str | None
    verification_url: str | None
    expires_at: datetime
    poll_interval_seconds: int
    error_code: str | None


def _view(flow: ProviderAuthFlow) -> DeviceFlowView:
    return DeviceFlowView(
        status=flow.status,
        user_code=flow.user_code if flow.status == AuthFlowStatus.PENDING.value else None,
        verification_url=flow.verification_url
        if flow.status == AuthFlowStatus.PENDING.value
        else None,
        expires_at=flow.expires_at,
        poll_interval_seconds=flow.poll_interval_seconds or 5,
        error_code=flow.error_code,
    )


async def start_yandex(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> DeviceFlowView:
    yandex = ctx.providers.yandex
    if yandex is None:
        raise ProviderUnavailable("Yandex Music is disabled on this server.")
    try:
        code = await yandex.start_device_flow(user_key=str(user_id))
    except ProviderError as exc:
        raise ServiceUnavailable(
            "Yandex did not respond. Please try again in a minute.", code=exc.code
        ) from exc
    await _cancel_pending_flows(db, ctx, user_id)
    now = ctx.clock()
    flow = ProviderAuthFlow(
        id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        provider=ProviderName.YANDEX.value,
        kind=AuthFlowKind.DEVICE_CODE.value,
        status=AuthFlowStatus.PENDING.value,
        user_code=code.user_code[:32],
        verification_url=code.verification_url[:255],
        poll_interval_seconds=code.interval,
        next_poll_at=now + timedelta(seconds=code.interval),
        created_at=now,
        expires_at=now + timedelta(seconds=max(30, code.expires_in)),
    )
    flow.secret_enc = ctx.cipher.encrypt(
        code.device_code, context=flow_context(flow.id, "device_code")
    )
    db.add(flow)
    await db.commit()
    return _view(flow)


async def _current_device_flow(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> ProviderAuthFlow:
    flow = (
        await db.execute(
            select(ProviderAuthFlow)
            .where(
                ProviderAuthFlow.user_id == user_id,
                ProviderAuthFlow.session_id == session_id,
                ProviderAuthFlow.provider == ProviderName.YANDEX.value,
                ProviderAuthFlow.kind == AuthFlowKind.DEVICE_CODE.value,
            )
            .order_by(ProviderAuthFlow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if flow is None:
        raise NotFound("No Yandex authorisation in progress.", code="no_pending_authorization")
    return flow


async def poll_yandex(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> DeviceFlowView:
    """Advance the device flow by at most one upstream poll, never blocking.

    The frontend calls this every ``poll_interval_seconds``; if it calls early
    we answer from the database without contacting Yandex.
    """
    flow = await _current_device_flow(db, user_id, session_id)
    now = ctx.clock()
    if flow.status != AuthFlowStatus.PENDING.value:
        return _view(flow)
    if flow.expires_at <= now:
        _finish(flow, AuthFlowStatus.EXPIRED, now, "expired")
        await db.commit()
        return _view(flow)
    if flow.next_poll_at is not None and flow.next_poll_at > now:
        return _view(flow)
    yandex = ctx.providers.yandex
    if yandex is None or flow.secret_enc is None:
        _finish(flow, AuthFlowStatus.FAILED, now, "provider_not_configured")
        await db.commit()
        return _view(flow)

    interval = flow.poll_interval_seconds or 5
    try:
        device_code = ctx.cipher.decrypt(
            flow.secret_enc, context=flow_context(flow.id, "device_code")
        )
        token = await yandex.poll_device_flow(device_code)
    except DeviceFlowPending as pending:
        if pending.slow_down:
            interval += 5
            flow.poll_interval_seconds = interval
        flow.next_poll_at = ctx.clock() + timedelta(seconds=interval)
        await db.commit()
        return _view(flow)
    except DeviceFlowError as failure:
        status = AuthFlowStatus.EXPIRED if failure.code == "expired" else AuthFlowStatus.FAILED
        _finish(flow, status, ctx.clock(), failure.code)
        await db.commit()
        return _view(flow)
    except ProviderError:
        flow.next_poll_at = ctx.clock() + timedelta(
            seconds=max(interval, _YANDEX_UNREACHABLE_BACKOFF)
        )
        await db.commit()
        return _view(flow)
    except DecryptionError:
        _finish(flow, AuthFlowStatus.FAILED, ctx.clock(), "decryption_failed")
        await db.commit()
        return _view(flow)

    tokens = TokenSet(
        access_token=token.access_token,
        refresh_token=None,  # yandex-music 3.2.2 cannot refresh; don't keep unused secrets
        expires_at=yandex.token_expiry(token),
    )
    _, replaced = await store_connection(
        db, ctx, user_id=user_id, provider=ProviderName.YANDEX, tokens=tokens
    )
    _finish(flow, AuthFlowStatus.COMPLETED, ctx.clock())
    await db.commit()
    await revoke_at_provider(ctx, replaced)
    return _view(flow)


async def cancel_yandex(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    flow = await _current_device_flow(db, user_id, session_id)
    if flow.status == AuthFlowStatus.PENDING.value:
        _finish(flow, AuthFlowStatus.CANCELLED, ctx.clock(), "cancelled")
        await db.commit()


async def pending_flow(
    db: AsyncSession, ctx: AppContext, user_id: uuid.UUID
) -> ProviderAuthFlow | None:
    return (
        await db.execute(
            select(ProviderAuthFlow)
            .where(
                ProviderAuthFlow.user_id == user_id,
                ProviderAuthFlow.status == AuthFlowStatus.PENDING.value,
                ProviderAuthFlow.expires_at > ctx.clock(),
            )
            .order_by(ProviderAuthFlow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
