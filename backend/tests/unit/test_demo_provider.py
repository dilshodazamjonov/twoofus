from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.providers.base import Credentials, PlaybackStatus
from app.providers.demo import CYCLE_MS, DEMO_TRACKS, DemoProvider, demo_playback_at

T0 = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def test_demo_is_deterministic_and_differs_per_subject() -> None:
    assert demo_playback_at(T0, "a") == demo_playback_at(T0, "a")
    states = {demo_playback_at(T0, key).identity() for key in ("a", "b", "c", "d", "e")}
    assert len(states) > 1


def test_demo_cycle_covers_playing_paused_and_idle_with_sane_progress() -> None:
    seen: set[PlaybackStatus] = set()
    for second in range(0, CYCLE_MS // 1000, 5):
        playback = demo_playback_at(T0 + timedelta(seconds=second), "subject")
        seen.add(playback.status)
        if playback.status is PlaybackStatus.IDLE:
            assert playback.track is None
            assert playback.progress_ms is None
            assert playback.is_playing is False
            continue
        assert playback.track is not None
        assert playback.track.track_url is None  # no fake link-outs
        assert playback.track.title in {t.title for t in DEMO_TRACKS}
        assert playback.progress_ms is not None
        assert 0 <= playback.progress_ms <= (playback.track.duration_ms or 0)
        assert playback.is_playing is (playback.status is PlaybackStatus.PLAYING)
    assert seen == {PlaybackStatus.PLAYING, PlaybackStatus.PAUSED, PlaybackStatus.IDLE}


async def test_demo_provider_uses_injected_clock() -> None:
    provider = DemoProvider(lambda: T0)
    result = await provider.fetch_playback(Credentials(None, None, None), subject_key="k")
    assert result.playback == demo_playback_at(T0, "k")
    assert result.new_tokens is None


async def test_recent_songs_are_distinct_newest_first() -> None:
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    provider = DemoProvider(lambda: now)
    result = await provider.fetch_recent(Credentials(None, None, None), subject_key="a", limit=3)
    assert len({t.key for t in result.tracks}) == 3
    times = [t.played_at for t in result.tracks]
    assert times == sorted(times, reverse=True)  # type: ignore[type-var]
    assert all(t.played_at is not None and t.played_at < now for t in result.tracks)
