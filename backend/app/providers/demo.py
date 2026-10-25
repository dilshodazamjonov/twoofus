"""Deterministic DEMO provider for development, screenshots and tests.

Everything here is invented and every response is flagged ``is_demo`` by the
service layer, so demo playback can never be mistaken for a real service.
The playlist loops on a fixed timeline that also exercises paused and idle
states; the phase depends on the subject key so the two members differ.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.models.enums import ProviderName
from app.providers.base import (
    ContentType,
    Credentials,
    FetchResult,
    PlaybackStatus,
    ProviderPlayback,
    TrackInfo,
)


@dataclass(frozen=True, slots=True)
class DemoTrack:
    title: str
    artists: tuple[str, ...]
    album: str
    duration_ms: int
    artwork: str


DEMO_TRACKS: tuple[DemoTrack, ...] = (
    DemoTrack("Paper Lanterns", ("Juniper Lane",), "Small Hours", 214_000, "/demo/cover-1.svg"),
    DemoTrack(
        "Window Seat",
        ("Mara Ellis", "The Quiet Hours"),
        "Late Trains",
        187_000,
        "/demo/cover-2.svg",
    ),
    DemoTrack("Kettle Song", ("Oslo Tea Club",), "Sunday Things", 163_000, "/demo/cover-3.svg"),
    DemoTrack(
        "Two Coats, One Umbrella", ("Bea & the Fog",), "Drizzle", 241_000, "/demo/cover-4.svg"
    ),
    DemoTrack("Northern Kitchen", ("Lumen Field",), "Warm Rooms", 198_000, "/demo/cover-5.svg"),
)


@dataclass(frozen=True, slots=True)
class _Segment:
    kind: Literal["play", "pause", "idle"]
    duration_ms: int
    track: int = 0
    # For "play": progress at segment start. For "pause": frozen progress.
    start_progress_ms: int = 0


def _build_timeline() -> tuple[_Segment, ...]:
    t = DEMO_TRACKS
    return (
        _Segment("play", t[0].duration_ms, 0),
        _Segment("play", 80_000, 1),
        _Segment("pause", 45_000, 1, start_progress_ms=80_000),
        _Segment("play", t[1].duration_ms - 80_000, 1, start_progress_ms=80_000),
        _Segment("play", t[2].duration_ms, 2),
        _Segment("idle", 60_000),
        _Segment("play", t[3].duration_ms, 3),
        _Segment("play", t[4].duration_ms, 4),
        _Segment("pause", 30_000, 4, start_progress_ms=t[4].duration_ms - 1_000),
    )


TIMELINE = _build_timeline()
CYCLE_MS = sum(s.duration_ms for s in TIMELINE)


def _offset_ms(subject_key: str) -> int:
    digest = hashlib.sha256(f"twoofus-demo:{subject_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % CYCLE_MS


def demo_playback_at(moment: datetime, subject_key: str) -> ProviderPlayback:
    position = (int(moment.timestamp() * 1000) + _offset_ms(subject_key)) % CYCLE_MS
    for segment in TIMELINE:
        if position < segment.duration_ms:
            break
        position -= segment.duration_ms
    else:  # pragma: no cover - position is always inside the cycle
        segment = TIMELINE[-1]
        position = 0

    if segment.kind == "idle":
        return ProviderPlayback(PlaybackStatus.IDLE, detail_code="nothing_playing")

    demo = DEMO_TRACKS[segment.track]
    track = TrackInfo(
        title=demo.title,
        artist_names=demo.artists,
        album=demo.album,
        artwork_url=demo.artwork,
        track_url=None,  # there is no real service to link to
        duration_ms=demo.duration_ms,
        provider_track_id=f"demo-{segment.track}",
    )
    if segment.kind == "pause":
        return ProviderPlayback(
            PlaybackStatus.PAUSED,
            content_type=ContentType.TRACK,
            track=track,
            progress_ms=segment.start_progress_ms,
        )
    return ProviderPlayback(
        PlaybackStatus.PLAYING,
        content_type=ContentType.TRACK,
        track=track,
        progress_ms=min(segment.start_progress_ms + position, demo.duration_ms),
    )


class DemoProvider:
    name = ProviderName.DEMO
    experimental = False

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def fetch_playback(self, credentials: Credentials, *, subject_key: str) -> FetchResult:
        del credentials  # the demo provider has no credentials
        return FetchResult(demo_playback_at(self._clock(), subject_key))
