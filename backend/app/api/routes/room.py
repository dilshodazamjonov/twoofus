"""The shared room: members and the two-person now-playing view."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Auth, Ctx, Db
from app.models import MemberRole
from app.schemas.room import (
    InvitationStatusOut,
    MemberNowPlayingOut,
    MemberOut,
    PlaybackOut,
    RoomNowPlayingOut,
    RoomOut,
)
from app.services import invitations
from app.services.members import MemberInfo, load_room_members
from app.services.now_playing import MemberPlayback, PlaybackView

router = APIRouter(tags=["room"])


def _member_out(info: MemberInfo, *, is_me: bool) -> MemberOut:
    reveal_provider = is_me or info.sharing_enabled
    return MemberOut(
        id=info.user.id,
        display_name=info.user.display_name,
        role=info.membership.role,  # type: ignore[arg-type]  # constrained by a CHECK
        is_me=is_me,
        joined_at=info.membership.joined_at,
        sharing_enabled=info.sharing_enabled,
        provider=(
            info.connection.provider  # type: ignore[arg-type]  # constrained by a CHECK
            if reveal_provider and info.connection is not None
            else None
        ),
    )


def playback_out(view: PlaybackView) -> PlaybackOut:
    track = view.track
    return PlaybackOut(
        source=view.source,  # type: ignore[arg-type]
        status=view.status.value,
        detail_code=view.detail_code,
        content_type=view.content_type.value if view.content_type else None,
        track_title=track.title if track else None,
        artist_names=list(track.artist_names) if track else [],
        album=track.album if track else None,
        artwork_url=track.artwork_url if track else None,
        track_url=track.track_url if track else None,
        duration_ms=track.duration_ms if track else None,
        progress_ms=view.progress_ms,
        is_playing=view.is_playing,
        fetched_at=view.fetched_at,
        last_changed_at=view.last_changed_at,
        is_stale=view.is_stale,
        is_demo=view.is_demo,
        experimental=view.experimental,
    )


def _member_now_playing(item: MemberPlayback) -> MemberNowPlayingOut:
    return MemberNowPlayingOut(
        user_id=item.member.user.id,
        display_name=item.member.user.display_name,
        is_me=item.is_me,
        sharing_enabled=item.member.sharing_enabled,
        playback=playback_out(item.playback),
    )


@router.get("/room", response_model=RoomOut, summary="My room and its members")
async def room(ctx: Ctx, db: Db, auth: Auth) -> RoomOut:
    members = await load_room_members(db, auth.user.id)
    out = [_member_out(members.me, is_me=True)]
    if members.partner is not None:
        out.append(_member_out(members.partner, is_me=False))
    invitation_out = None
    if auth.membership.role == MemberRole.OWNER.value:
        pending = await invitations.current_invitation(db, ctx, members.room_id)
        invitation_out = (
            InvitationStatusOut(
                pending=True, created_at=pending.created_at, expires_at=pending.expires_at
            )
            if pending
            else InvitationStatusOut(pending=False)
        )
    return RoomOut(
        id=members.room_id, app_name=ctx.settings.app_name, members=out, invitation=invitation_out
    )


@router.get(
    "/room/now-playing",
    response_model=RoomNowPlayingOut,
    summary="What both members are listening to (consent-filtered, cached)",
)
async def now_playing(ctx: Ctx, db: Db, auth: Auth) -> RoomNowPlayingOut:
    members = await load_room_members(db, auth.user.id)
    await db.close()  # release the connection before (possibly slow) provider calls
    view = await ctx.now_playing.room_view(members)
    return RoomNowPlayingOut(
        generated_at=view.generated_at,
        poll_after_seconds=view.poll_after_seconds,
        me=_member_now_playing(view.me),
        partner=_member_now_playing(view.partner) if view.partner else None,
        partner_joined=members.partner is not None,
    )
