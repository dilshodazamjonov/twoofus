"""Recent songs, the song picked for the other member, the shared playlist and
the question of the day."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import Auth, Ctx, Db
from app.core.ratelimit import SONGS_PER_USER
from app.schemas.songs import (
    AnswerIn,
    MemberRecentOut,
    PlaylistEntryOut,
    QuestionOut,
    RecentTrackOut,
    RoomRecentOut,
    SongKeyIn,
    SongOut,
    SongsOut,
)
from app.services import questions, songs
from app.services.members import load_room_members
from app.services.now_playing import MemberRecent
from app.services.questions import QuestionView
from app.services.songs import SongsView, SongView

router = APIRouter(prefix="/room", tags=["songs"])


def _member_recent(item: MemberRecent) -> MemberRecentOut:
    recent = item.recent
    return MemberRecentOut(
        user_id=item.member.user.id,
        is_me=item.is_me,
        state=recent.state,
        source=recent.source,  # type: ignore[arg-type]  # a ProviderName value
        tracks=[
            RecentTrackOut(
                key=t.key,
                title=t.title,
                artist_names=list(t.artist_names),
                artwork_url=t.artwork_url,
                track_url=t.track_url,
                played_at=t.played_at,
                played_on=t.played_on,
            )
            for t in recent.tracks
        ],
    )


def _song(view: SongView) -> SongOut:
    return SongOut(
        provider=view.provider,  # type: ignore[arg-type]  # a ProviderName value
        title=view.title,
        artist_names=list(view.artist_names),
        artwork_url=view.artwork_url,
        track_url=view.track_url,
        created_at=view.created_at,
    )


def _songs(view: SongsView) -> SongsOut:
    return SongsOut(
        for_me=_song(view.for_me) if view.for_me else None,
        from_me=_song(view.from_me) if view.from_me else None,
        playlist=[
            PlaylistEntryOut(id=e.id, song=_song(e.song), added_by_me=e.added_by_me)
            for e in view.playlist
        ],
    )


def _question(view: QuestionView) -> QuestionOut:
    return QuestionOut(
        day=view.day,
        question=view.question,
        my_answer=view.my_answer,
        partner_answer=view.partner_answer,
    )


@router.get(
    "/recent",
    response_model=RoomRecentOut,
    summary="Both members' last few songs (consent-filtered, cached)",
)
async def recent(ctx: Ctx, db: Db, auth: Auth) -> RoomRecentOut:
    members = await load_room_members(db, auth.user.id)
    await db.close()  # release the connection before (possibly slow) provider calls
    me, partner = await ctx.now_playing.room_recent(members)
    return RoomRecentOut(
        me=_member_recent(me), partner=_member_recent(partner) if partner else None
    )


@router.get("/songs", response_model=SongsOut, summary="Picked songs and the shared playlist")
async def list_songs(ctx: Ctx, db: Db, auth: Auth) -> SongsOut:
    return _songs(await songs.songs(db, ctx, user_id=auth.user.id))


@router.put("/songs/pick", response_model=SongsOut, summary="Pick a recent song for the other")
async def pick(body: SongKeyIn, ctx: Ctx, db: Db, auth: Auth) -> SongsOut:
    ctx.rate_limiter.check(f"songs:{auth.user.id}", SONGS_PER_USER)
    return _songs(await songs.pick_song(db, ctx, user_id=auth.user.id, key=body.key))


@router.delete("/songs/pick", response_model=SongsOut, summary="Take your pick back")
async def unpick(ctx: Ctx, db: Db, auth: Auth) -> SongsOut:
    ctx.rate_limiter.check(f"songs:{auth.user.id}", SONGS_PER_USER)
    return _songs(await songs.clear_pick(db, ctx, user_id=auth.user.id))


@router.post(
    "/songs/playlist", response_model=SongsOut, summary="Add a recent song to the playlist"
)
async def add(body: SongKeyIn, ctx: Ctx, db: Db, auth: Auth) -> SongsOut:
    ctx.rate_limiter.check(f"songs:{auth.user.id}", SONGS_PER_USER)
    return _songs(await songs.add_to_playlist(db, ctx, user_id=auth.user.id, key=body.key))


@router.delete(
    "/songs/playlist/{item_id}", response_model=SongsOut, summary="Remove a playlist song"
)
async def remove(item_id: uuid.UUID, ctx: Ctx, db: Db, auth: Auth) -> SongsOut:
    ctx.rate_limiter.check(f"songs:{auth.user.id}", SONGS_PER_USER)
    return _songs(await songs.remove_from_playlist(db, ctx, user_id=auth.user.id, item_id=item_id))


@router.get("/question", response_model=QuestionOut, summary="Today's question and answers")
async def question(ctx: Ctx, db: Db, auth: Auth) -> QuestionOut:
    return _question(await questions.today(db, ctx, user_id=auth.user.id))


@router.put("/question", response_model=QuestionOut, summary="Answer today's question")
async def answer(body: AnswerIn, ctx: Ctx, db: Db, auth: Auth) -> QuestionOut:
    ctx.rate_limiter.check(f"songs:{auth.user.id}", SONGS_PER_USER)
    return _question(await questions.answer(db, ctx, user_id=auth.user.id, text=body.answer))
