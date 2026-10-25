"""Owner issues one invitation; the partner inspects and accepts it."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import Ctx, Db, OptionalAuth, Owner, client_ip
from app.api.routes.auth import start_session
from app.core.errors import Conflict
from app.core.ratelimit import INVITE_CREATE_PER_USER, INVITE_PER_IP
from app.schemas.auth import SessionOut
from app.schemas.room import (
    InvitationAcceptIn,
    InvitationCreatedOut,
    InvitationInspectOut,
    InvitationStatusOut,
    InvitationTokenIn,
)
from app.services import invitations

router = APIRouter(tags=["invitations"])


@router.post(
    "/invitations",
    response_model=InvitationCreatedOut,
    status_code=201,
    summary="Owner: create the (single, short-lived) partner invitation",
)
async def create_invitation(ctx: Ctx, db: Db, auth: Owner) -> InvitationCreatedOut:
    ctx.rate_limiter.check(f"invite-create:user:{auth.user.id}", INVITE_CREATE_PER_USER)
    created = await invitations.create_invitation(
        db, ctx, room_id=auth.membership.room_id, owner_id=auth.user.id
    )
    # The token travels in the URL fragment, which browsers never send to the
    # server, so it stays out of access logs and Referer headers.
    return InvitationCreatedOut(
        invite_url=f"{ctx.settings.public_app_url}/invite#token={created.token}",
        token=created.token,
        expires_at=created.expires_at,
    )


@router.get(
    "/invitations/current",
    response_model=InvitationStatusOut,
    summary="Owner: is an invitation pending?",
)
async def current_invitation(ctx: Ctx, db: Db, auth: Owner) -> InvitationStatusOut:
    invitation = await invitations.current_invitation(db, ctx, auth.membership.room_id)
    if invitation is None:
        return InvitationStatusOut(pending=False)
    return InvitationStatusOut(
        pending=True, created_at=invitation.created_at, expires_at=invitation.expires_at
    )


@router.delete("/invitations/current", status_code=204, summary="Owner: revoke the invitation")
async def revoke_invitation(ctx: Ctx, db: Db, auth: Owner) -> Response:
    await invitations.revoke_pending(db, ctx, auth.membership.room_id)
    return Response(status_code=204)


@router.post(
    "/invitations/inspect",
    response_model=InvitationInspectOut,
    summary="Public: check an invitation token before accepting",
)
async def inspect_invitation(
    body: InvitationTokenIn, request: Request, ctx: Ctx, db: Db
) -> InvitationInspectOut:
    ctx.rate_limiter.check(f"invite:ip:{client_ip(request)}", INVITE_PER_IP)
    invitation, inviter = await invitations.inspect_invitation(db, ctx, body.token)
    return InvitationInspectOut(
        app_name=ctx.settings.app_name,
        inviter_display_name=inviter,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/invitations/accept",
    response_model=SessionOut,
    status_code=201,
    summary="Public: accept an invitation, create the partner account and sign in",
)
async def accept_invitation(
    body: InvitationAcceptIn,
    request: Request,
    response: Response,
    ctx: Ctx,
    db: Db,
    auth: OptionalAuth,
) -> SessionOut:
    ctx.rate_limiter.check(f"invite:ip:{client_ip(request)}", INVITE_PER_IP)
    if auth is not None:
        raise Conflict("Sign out before accepting an invitation.", code="already_signed_in")
    user = await invitations.accept_invitation(
        db,
        ctx,
        token=body.token,
        username=body.username,
        display_name=body.display_name,
        password=body.password,
    )
    response.status_code = 201
    return await start_session(db, ctx, response, user)
