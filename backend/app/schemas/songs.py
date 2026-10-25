from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel, OutModel
from app.schemas.room import ProviderLiteral


class RecentTrackOut(OutModel):
    key: str = Field(description="Send it back to pick this song or add it to the playlist.")
    title: str
    artist_names: list[str]
    artwork_url: str | None
    track_url: str | None
    played_at: datetime | None = Field(description="When it was played (Spotify).")
    played_on: date | None = Field(description="The day it was played (Yandex reports no time).")


class MemberRecentOut(OutModel):
    user_id: uuid.UUID
    is_me: bool
    state: Literal["ok", "needs_permission", "unavailable", "private", "not_connected"] = Field(
        description="needs_permission: the music service grant predates recent songs; "
        "private: not shared with you."
    )
    source: ProviderLiteral | None
    tracks: list[RecentTrackOut] = Field(description="Newest first, each song once.")


class RoomRecentOut(OutModel):
    me: MemberRecentOut
    partner: MemberRecentOut | None


class SongOut(OutModel):
    provider: ProviderLiteral
    title: str
    artist_names: list[str]
    artwork_url: str | None
    track_url: str | None
    created_at: datetime


class PlaylistEntryOut(OutModel):
    id: uuid.UUID
    song: SongOut
    added_by_me: bool


class SongsOut(OutModel):
    for_me: SongOut | None = Field(description="The song the other member picked for you.")
    from_me: SongOut | None = Field(description="The song you picked for them.")
    playlist: list[PlaylistEntryOut] = Field(description="Newest first.")


class SongKeyIn(ApiModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[0-9A-Za-z-]+$")


class QuestionOut(OutModel):
    day: date = Field(description="The UTC day the question belongs to.")
    question: str
    my_answer: str | None
    partner_answer: str | None = Field(description="Only shown once you have answered too.")


class AnswerIn(ApiModel):
    answer: str = Field(min_length=1, max_length=280)
