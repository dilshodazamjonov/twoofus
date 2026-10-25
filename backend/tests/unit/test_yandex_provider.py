"""Yandex adapter: mapping logic with a fake gateway, plus checks against the
*installed* yandex-music 3.2.2 models/exceptions (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import yandex_music
from yandex_music.exceptions import DeviceAuthError, NetworkError, YnisonUnauthorizedError
from yandex_music.ynison.models import ynison_state

from app.providers.base import ContentType, Credentials, PlaybackStatus, ProviderError
from app.providers.yandex import (
    DeviceFlowError,
    DeviceFlowPending,
    LibraryYandexGateway,
    YandexProvider,
    YandexToken,
    YandexTrackMeta,
    YnisonPlayable,
    YnisonSnapshot,
    snapshot_from_ynison_state,
    yandex_cover_url,
    ynison_device_id,
)
from tests.conftest import FakeYandexGateway, yandex_playing

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TOKEN = Credentials(
    access_token="ym-token", refresh_token=None, expires_at=NOW + timedelta(days=300)
)


def test_pinned_library_version() -> None:
    # docs/INTEGRATIONS.md documents behaviour verified against exactly this version.
    assert yandex_music.__version__ == "3.2.2"


def make_provider(gateway: FakeYandexGateway) -> YandexProvider:
    return YandexProvider(
        gateway, app_name="Two of Us", web_base="https://music.yandex.ru", clock=lambda: NOW
    )


async def test_idle_without_active_device() -> None:
    gateway = FakeYandexGateway()
    result = await make_provider(gateway).fetch_playback(TOKEN, subject_key="conn-1")
    assert result.playback.status is PlaybackStatus.IDLE
    assert gateway.calls["track"] == 0
    assert gateway.tokens_seen == ["ym-token"]


async def test_playing_track_with_metadata_and_link() -> None:
    gateway = FakeYandexGateway(snapshot=yandex_playing())
    gateway.tracks["10994777"] = YandexTrackMeta(
        title="Real Title",
        artist_names=("Artist A", "Artist B"),
        album_title="Album",
        album_id="1193829",
        cover_uri="avatars.yandex.net/get-music-content/999/cover/%%",
        duration_ms=199_000,
    )
    playback = (await make_provider(gateway).fetch_playback(TOKEN, subject_key="c")).playback
    assert playback.status is PlaybackStatus.PLAYING
    assert playback.is_playing is True
    assert playback.content_type is ContentType.TRACK
    track = playback.track
    assert track is not None
    assert track.title == "Real Title"
    assert track.artist_names == ("Artist A", "Artist B")
    assert track.album == "Album"
    assert track.track_url == "https://music.yandex.ru/album/1193829/track/10994777"
    assert track.artwork_url == "https://avatars.yandex.net/get-music-content/999/cover/400x400"
    assert track.duration_ms == 200_000  # Ynison status duration wins
    assert playback.progress_ms == 42_000


async def test_paused_and_metadata_cache() -> None:
    gateway = FakeYandexGateway(snapshot=yandex_playing(paused=True))
    gateway.tracks["10994777"] = YandexTrackMeta("T", ("A",), None, None, None, None)
    provider = make_provider(gateway)
    first = await provider.fetch_playback(TOKEN, subject_key="c")
    second = await provider.fetch_playback(TOKEN, subject_key="c")
    assert first.playback.status is PlaybackStatus.PAUSED
    assert first.playback.is_playing is False
    assert second.playback == first.playback
    assert gateway.calls["track"] == 1  # metadata cached per track id


async def test_metadata_failure_degrades_to_ynison_fields() -> None:
    gateway = FakeYandexGateway(snapshot=yandex_playing())  # no metadata registered -> None
    track = (await make_provider(gateway).fetch_playback(TOKEN, subject_key="c")).playback.track
    assert track is not None
    assert track.title == "Ynison Title"
    assert track.artist_names == ()  # unknown, not invented
    assert track.artwork_url == "https://avatars.yandex.net/get-music-content/123/abc/400x400"


async def test_non_track_and_untitled_content() -> None:
    snapshot = YnisonSnapshot(
        True, False, 1000, None, YnisonPlayable("x", None, "video_clip", "Clip", None)
    )
    playback = (
        await make_provider(FakeYandexGateway(snapshot=snapshot)).fetch_playback(
            TOKEN, subject_key="c"
        )
    ).playback
    assert playback.content_type is ContentType.OTHER
    assert playback.track is None
    untitled = YnisonSnapshot(
        True, False, 1000, None, YnisonPlayable("123", None, "track", None, None)
    )
    playback = (
        await make_provider(FakeYandexGateway(snapshot=untitled)).fetch_playback(
            TOKEN, subject_key="c"
        )
    ).playback
    assert playback.detail_code == "incomplete_metadata"
    assert playback.track is None


async def test_local_track_has_no_link() -> None:
    snapshot = YnisonSnapshot(
        True, False, 5, 100, YnisonPlayable("loc-1", None, "local_track", "My File", None)
    )
    playback = (
        await make_provider(FakeYandexGateway(snapshot=snapshot)).fetch_playback(
            TOKEN, subject_key="c"
        )
    ).playback
    assert playback.content_type is ContentType.LOCAL_TRACK
    assert playback.track is not None
    assert playback.track.track_url is None


async def test_expired_or_missing_token_requires_reauth() -> None:
    provider = make_provider(FakeYandexGateway())
    for credentials in (
        Credentials(None, None, None),
        Credentials("t", None, NOW - timedelta(seconds=1)),
    ):
        with pytest.raises(ProviderError) as excinfo:
            await provider.fetch_playback(credentials, subject_key="c")
        assert excinfo.value.reauth_required


async def test_gateway_errors_propagate() -> None:
    gateway = FakeYandexGateway(snapshot=ProviderError("provider_unreachable"))
    with pytest.raises(ProviderError):
        await make_provider(gateway).fetch_playback(TOKEN, subject_key="c")


async def test_device_flow_helpers() -> None:
    gateway = FakeYandexGateway(poll_results=[None, YandexToken("tok", 31_536_000)])
    provider = make_provider(gateway)
    code = await provider.start_device_flow()
    assert gateway.device_names == ["Two of Us"]
    with pytest.raises(DeviceFlowPending):
        await provider.poll_device_flow(code.device_code)
    token = await provider.poll_device_flow(code.device_code)
    assert provider.token_expiry(token) == NOW + timedelta(seconds=31_536_000)
    assert provider.token_expiry(YandexToken("t", None)) is None


def test_cover_url_and_device_id_helpers() -> None:
    assert yandex_cover_url("avatars.yandex.net/a/%%") == "https://avatars.yandex.net/a/400x400"
    assert (
        yandex_cover_url("http://avatars.yandex.net/a/%%") == "https://avatars.yandex.net/a/400x400"
    )
    assert yandex_cover_url("//avatars.yandex.net/a/%%") == "https://avatars.yandex.net/a/400x400"
    assert yandex_cover_url("evil.example/a/%%") is None
    assert yandex_cover_url(None) is None
    assert ynison_device_id("c1") == ynison_device_id("c1") != ynison_device_id("c2")
    assert len(ynison_device_id("c1")) == 12


# ----- against the real library objects ------------------------------------------------


def _state(**kwargs: Any) -> ynison_state.PutYnisonStateResponse:
    playable = ynison_state.Playable(
        playable_id="10994777",
        album_id_optional="1193829",
        playable_type=ynison_state.PlayablePlayableType.TRACK,
        title="Title From Queue",
        cover_url_optional="avatars.yandex.net/get-music-content/1/2/%%",
    )
    status = ynison_state.PlayingStatus(
        progress_ms=10_000,
        duration_ms=180_000,
        paused=kwargs.get("paused", False),
        playback_speed=1.0,
        version=ynison_state.UpdateVersion(
            device_id="phone", version=1, timestamp_ms=kwargs.get("ts", 0)
        ),
    )
    queue = ynison_state.PlayerQueue(
        current_playable_index=kwargs.get("index", 0), playable_list=[playable]
    )
    device = ynison_state.Device(
        info=ynison_state.DeviceInfo(device_id="phone", title="iPhone"),
        is_offline=kwargs.get("offline", False),
    )
    return ynison_state.PutYnisonStateResponse(
        player_state=ynison_state.PlayerState(status=status, player_queue=queue),
        devices=[device],
        active_device_id_optional=kwargs.get("active", "phone"),
    )


def test_snapshot_from_real_ynison_models() -> None:
    snapshot = snapshot_from_ynison_state(_state(), now_ms=0)
    assert snapshot.has_active_device
    assert not snapshot.paused
    assert snapshot.duration_ms == 180_000
    assert snapshot.progress_ms == 10_000
    assert snapshot.playable == YnisonPlayable(
        "10994777",
        "1193829",
        "track",
        "Title From Queue",
        "avatars.yandex.net/get-music-content/1/2/%%",
    )


def test_snapshot_progress_extrapolates_only_while_playing() -> None:
    playing = snapshot_from_ynison_state(_state(ts=1_000_000), now_ms=1_005_000)
    assert playing.progress_ms == 15_000
    paused = snapshot_from_ynison_state(_state(ts=1_000_000, paused=True), now_ms=1_005_000)
    assert paused.progress_ms == 10_000


def test_snapshot_without_active_device_or_track() -> None:
    assert not snapshot_from_ynison_state(_state(active=""), now_ms=0).has_active_device
    assert not snapshot_from_ynison_state(_state(offline=True), now_ms=0).has_active_device
    assert snapshot_from_ynison_state(_state(index=-1), now_ms=0).playable is None


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (DeviceAuthError("slow_down"), DeviceFlowPending),
        (DeviceAuthError("expired_token: code expired"), DeviceFlowError),
        (DeviceAuthError("access_denied"), DeviceFlowError),
        (DeviceAuthError("invalid_client"), DeviceFlowError),
        (NetworkError("boom"), ProviderError),
    ],
)
async def test_library_gateway_maps_real_exceptions(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, expected: type[Exception]
) -> None:
    async def fake_poll(self: Any, device_code: str, *args: Any, **kwargs: Any) -> Any:
        raise raised

    monkeypatch.setattr(yandex_music.ClientAsync, "poll_device_token", fake_poll)
    with pytest.raises(expected) as excinfo:
        await LibraryYandexGateway(timeout_seconds=2).poll_device_token("code")
    if isinstance(excinfo.value, DeviceFlowPending):
        assert excinfo.value.slow_down
    if isinstance(excinfo.value, DeviceFlowError):
        assert excinfo.value.code in {"expired", "denied", "failed"}


async def test_library_gateway_pending_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    results: list[Any] = [None, yandex_music.OAuthToken(access_token="tok", expires_in=100)]

    async def fake_poll(self: Any, device_code: str, *args: Any, **kwargs: Any) -> Any:
        return results.pop(0)

    monkeypatch.setattr(yandex_music.ClientAsync, "poll_device_token", fake_poll)
    gateway = LibraryYandexGateway(timeout_seconds=2)
    assert await gateway.poll_device_token("code") is None
    assert await gateway.poll_device_token("code") == YandexToken("tok", 100)


async def test_library_gateway_maps_ynison_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import asynccontextmanager

    from yandex_music.ynison import YnisonClientAsync

    @asynccontextmanager
    async def fake_session(self: Any, timeout: float = 10.0) -> Any:
        raise YnisonUnauthorizedError(message="bad token", http_code=401)
        yield self  # pragma: no cover

    monkeypatch.setattr(YnisonClientAsync, "session", fake_session)
    with pytest.raises(ProviderError) as excinfo:
        await LibraryYandexGateway(timeout_seconds=2).fetch_player_state(
            "tok", device_id="abcdef123456", device_title="Two of Us (read-only)"
        )
    assert excinfo.value.reauth_required


async def test_library_gateway_fetch_track_with_real_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yandex_music import Album, Artist, Track

    seen: list[Any] = []

    async def fake_tracks(self: Any, track_ids: Any, *args: Any, **kwargs: Any) -> list[Track]:
        seen.append((self.token, track_ids))
        return [
            Track(
                id="10994777",
                title="Real Song",
                artists=[Artist(name="Singer"), Artist(name=None)],
                albums=[Album(id=1193829, title="Real Album", cover_uri="avatars.yandex.net/a/%%")],
                cover_uri=None,
                duration_ms=180_000,
            )
        ]

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", fake_tracks)
    meta = await LibraryYandexGateway(timeout_seconds=2).fetch_track("tok", "10994777")
    assert seen == [("tok", ["10994777"])]
    assert meta == YandexTrackMeta(
        title="Real Song",
        artist_names=("Singer",),
        album_title="Real Album",
        album_id="1193829",
        cover_uri="avatars.yandex.net/a/%%",  # falls back to the album cover
        duration_ms=180_000,
    )


async def test_library_gateway_fetch_track_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from yandex_music.exceptions import UnauthorizedError

    async def unauthorized(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise UnauthorizedError("bad token")

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", unauthorized)
    with pytest.raises(ProviderError) as excinfo:
        await LibraryYandexGateway(timeout_seconds=2).fetch_track("tok", "1")
    assert excinfo.value.reauth_required

    async def flaky(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NetworkError("down")

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", flaky)
    assert await LibraryYandexGateway(timeout_seconds=2).fetch_track("tok", "1") is None

    async def empty(self: Any, *args: Any, **kwargs: Any) -> Any:
        return []

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", empty)
    assert await LibraryYandexGateway(timeout_seconds=2).fetch_track("tok", "1") is None


async def test_library_gateway_device_code_with_real_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names: list[str | None] = []

    async def fake_request(
        self: Any, device_id: Any = None, device_name: Any = None, client_id: Any = None
    ) -> Any:
        names.append(device_name)
        return yandex_music.DeviceCode(
            device_code="dc",
            user_code="UC",
            verification_url="https://ya.ru/device",
            expires_in=300,
            interval=5,
        )

    monkeypatch.setattr(yandex_music.ClientAsync, "request_device_code", fake_request)
    code = await LibraryYandexGateway(timeout_seconds=2).request_device_code(
        device_name="Two of Us"
    )
    assert names == ["Two of Us"]
    assert (code.user_code, code.verification_url, code.expires_in, code.interval) == (
        "UC",
        "https://ya.ru/device",
        300,
        5,
    )

    async def failing(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NetworkError("down")

    monkeypatch.setattr(yandex_music.ClientAsync, "request_device_code", failing)
    with pytest.raises(ProviderError):
        await LibraryYandexGateway(timeout_seconds=2).request_device_code(device_name="x")


async def test_library_gateway_reads_state_through_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager

    from yandex_music.exceptions import YnisonServerError, YnisonTimeoutError
    from yandex_music.ynison import YnisonClientAsync

    created: list[dict[str, Any]] = []
    original_init = YnisonClientAsync.__init__

    def spy_init(self: Any, token: str, **kwargs: Any) -> None:
        created.append(kwargs)
        original_init(self, token, **kwargs)

    state = _state()

    @asynccontextmanager
    async def fake_session(self: Any, timeout: float = 10.0) -> Any:
        class Connected:
            pass

        connected = Connected()
        connected.state = state  # type: ignore[attr-defined]
        yield connected

    monkeypatch.setattr(YnisonClientAsync, "__init__", spy_init)
    monkeypatch.setattr(YnisonClientAsync, "session", fake_session)
    snapshot = await LibraryYandexGateway(timeout_seconds=2).fetch_player_state(
        "tok", device_id="abcdef123456", device_title="Two of Us (read-only)"
    )
    assert snapshot.playable is not None
    assert snapshot.playable.playable_id == "10994777"
    assert created == [
        {
            "device_id": "abcdef123456",
            "device_title": "Two of Us (read-only)",
            "max_reconnect_attempts": 1,
        }
    ]

    for error, code, retry in (
        (YnisonServerError(message="go away", go_away_seconds=60), "provider_rate_limited", 60.0),
        (
            YnisonServerError(message="busy", backoff_ms=[0, 1000, 5000]),
            "provider_unreachable",
            5.0,
        ),
        (YnisonTimeoutError("slow"), "provider_unreachable", None),
    ):

        @asynccontextmanager
        async def failing_session(
            self: Any, timeout: float = 10.0, _error: Exception = error
        ) -> Any:
            raise _error
            yield self  # pragma: no cover

        monkeypatch.setattr(YnisonClientAsync, "session", failing_session)
        with pytest.raises(ProviderError) as excinfo:
            await LibraryYandexGateway(timeout_seconds=2).fetch_player_state(
                "tok", device_id="abcdef123456", device_title="t (read-only)"
            )
        assert (excinfo.value.code, excinfo.value.retry_after_seconds) == (code, retry)
