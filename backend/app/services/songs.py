"""Songs the members share on purpose: one pick for the other member, and a
shared playlist.

* A member can only share a song from their own recently played list, as
  their music service reported it (``NowPlayingService.recent_for``). Nothing
  is typed or pasted, so titles, covers and links come from the service.
* The playlist holds at most ``MAX_PLAYLIST`` songs, each once. Either member
  can remove any of them: it is shared.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.context import AppContext
from app.core.errors import Conflict
from app.models import PlaylistItem, SongPick
from app.models.songs import TrackSnapshot
from app.providers.base import RecentTrack
from app.services.members import RoomMembers, load_room_members
from app.services.tulips import NoPartner

MAX_PLAYLIST = 50


class NotRecent(Conflict):
    code = "song_not_recent"
    message = "That song is no longer in your recent list."


class PlaylistFull(Conflict):
    code = "playlist_full"
    message = "The playlist is full."


@dataclass(frozen=True, slots=True)
class SongView:
    provider: str
    title: str
    artist_names: tuple[str, ...]
    artwork_url: str | None
    track_url: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PlaylistEntryView:
    id: uuid.UUID
    song: SongView
    added_by_me: bool


@dataclass(frozen=True, slots=True)
class SongsView:
    for_me: SongView | None
    from_me: SongView | None
    playlist: list[PlaylistEntryView]


def _view(row: SongPick | PlaylistItem) -> SongView:
    return SongView(
        provider=row.provider,
        title=row.title,
        artist_names=tuple(row.artist_names),
        artwork_url=row.artwork_url,
        track_url=row.track_url,
        created_at=row.created_at,
    )


def _copy(target: TrackSnapshot, provider: str, track: RecentTrack) -> None:
    def url(value: str | None) -> str | None:
        return value if value is not None and len(value) <= 500 else None

    target.provider = provider
    target.track_key = track.key
    target.title = track.title[:200]
    target.artist_names = [name[:100] for name in track.artist_names[:10]]
    target.artwork_url = url(track.artwork_url)
    target.track_url = url(track.track_url)


async def _recent_track(ctx: AppContext, members: RoomMembers, key: str) -> tuple[str, RecentTrack]:
    connection = members.me.connection
    if connection is not None:
        recent = await ctx.now_playing.recent_for(connection)
        for track in recent.tracks:
            if track.key == key and recent.source is not None:
                return recent.source, track
    raise NotRecent


async def songs(db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID) -> SongsView:
    del ctx
    members = await load_room_members(db, user_id)
    picks = (
        (await db.execute(select(SongPick).where(SongPick.room_id == members.room_id)))
        .scalars()
        .all()
    )
    for_me = next((p for p in picks if p.recipient_id == user_id), None)
    from_me = next((p for p in picks if p.sender_id == user_id), None)
    items = await db.execute(
        select(PlaylistItem)
        .where(PlaylistItem.room_id == members.room_id)
        .order_by(PlaylistItem.created_at.desc(), PlaylistItem.id.desc())
    )
    return SongsView(
        for_me=_view(for_me) if for_me else None,
        from_me=_view(from_me) if from_me else None,
        playlist=[
            PlaylistEntryView(id=item.id, song=_view(item), added_by_me=item.added_by == user_id)
            for item in items.scalars()
        ],
    )


async def pick_song(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, key: str
) -> SongsView:
    members = await load_room_members(db, user_id)
    if members.partner is None:
        raise NoPartner
    await db.close()  # release the connection before a possible provider call
    provider, track = await _recent_track(ctx, members, key)
    await db.execute(delete(SongPick).where(SongPick.sender_id == user_id))
    pick = SongPick(
        id=uuid.uuid4(),
        room_id=members.room_id,
        sender_id=user_id,
        recipient_id=members.partner.user.id,
        created_at=ctx.clock(),
    )
    _copy(pick, provider, track)
    db.add(pick)
    await db.commit()
    return await songs(db, ctx, user_id=user_id)


async def clear_pick(db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID) -> SongsView:
    await db.execute(delete(SongPick).where(SongPick.sender_id == user_id))
    await db.commit()
    return await songs(db, ctx, user_id=user_id)


async def add_to_playlist(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, key: str
) -> SongsView:
    members = await load_room_members(db, user_id)
    await db.close()  # release the connection before a possible provider call
    provider, track = await _recent_track(ctx, members, key)
    room = PlaylistItem.room_id == members.room_id
    exists = (
        await db.execute(
            select(PlaylistItem.id).where(
                room, PlaylistItem.provider == provider, PlaylistItem.track_key == track.key
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        count = (
            await db.execute(select(func.count()).select_from(PlaylistItem).where(room))
        ).scalar_one()
        if count >= MAX_PLAYLIST:
            raise PlaylistFull
        item = PlaylistItem(
            id=uuid.uuid4(), room_id=members.room_id, added_by=user_id, created_at=ctx.clock()
        )
        _copy(item, provider, track)
        db.add(item)
        try:
            await db.commit()
        except IntegrityError:  # the same song, added twice at once: one is enough
            await db.rollback()
    return await songs(db, ctx, user_id=user_id)


async def remove_from_playlist(
    db: AsyncSession, ctx: AppContext, *, user_id: uuid.UUID, item_id: uuid.UUID
) -> SongsView:
    members = await load_room_members(db, user_id)
    await db.execute(
        delete(PlaylistItem).where(
            PlaylistItem.id == item_id, PlaylistItem.room_id == members.room_id
        )
    )
    await db.commit()
    return await songs(db, ctx, user_id=user_id)
