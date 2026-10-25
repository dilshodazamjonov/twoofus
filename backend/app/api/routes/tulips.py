"""Tulips: a small signal between the two members."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Auth, Ctx, Db
from app.core.ratelimit import TULIP_PER_DAY, TULIP_PER_MINUTE
from app.schemas.tulips import TulipOut, TulipsOut
from app.services import tulips
from app.services.tulips import TulipsView, TulipView

router = APIRouter(prefix="/room/tulips", tags=["tulips"])


def tulip_out(view: TulipView) -> TulipOut:
    return TulipOut(
        id=view.id,
        direction=view.direction,
        created_at=view.created_at,
        is_new=view.is_new,
    )


def tulips_out(view: TulipsView) -> TulipsOut:
    return TulipsOut(items=[tulip_out(item) for item in view.items], unseen_count=view.unseen_count)


@router.get("", response_model=TulipsOut, summary="Recent tulips sent and received")
async def list_tulips(ctx: Ctx, db: Db, auth: Auth) -> TulipsOut:
    return tulips_out(await tulips.recent_tulips(db, ctx, user_id=auth.user.id))


@router.post("", response_model=TulipOut, status_code=201, summary="Send a tulip")
async def send_tulip(ctx: Ctx, db: Db, auth: Auth) -> TulipOut:
    ctx.rate_limiter.check(f"tulip:minute:{auth.user.id}", TULIP_PER_MINUTE)
    ctx.rate_limiter.check(f"tulip:day:{auth.user.id}", TULIP_PER_DAY)
    return tulip_out(await tulips.send_tulip(db, ctx, sender_id=auth.user.id))


@router.post("/seen", response_model=TulipsOut, summary="Mark the tulips you received as seen")
async def mark_seen(ctx: Ctx, db: Db, auth: Auth) -> TulipsOut:
    await tulips.mark_seen(db, ctx, user_id=auth.user.id)
    return tulips_out(await tulips.recent_tulips(db, ctx, user_id=auth.user.id))
