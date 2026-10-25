"""Yandex adapter: mapping logic with a fake gateway, plus checks against the
*installed* yandex-music 3.2.2 models/exceptions (no network)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
import yandex_music
from yandex_music.exceptions import NetworkError, YnisonUnauthorizedError
from yandex_music.ynison.models import ynison_state

from app.providers.base import ContentType, Credentials, PlaybackStatus, ProviderError
from app.providers.yandex import (
    OAUTH_BASE,
    DeviceFlowError,
    DeviceFlowPending,
    LibraryYandexGateway,
    YandexHistoryTrack,
    YandexProvider,
    YandexToken,
    YandexTrackMeta,
    YnisonPlayable,
    YnisonSnapshot,
    _ynison_client_class,
    history_tracks,
    music_app_credentials,
    oauth_device_id,
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
    # The integration was verified against exactly this version.
    assert yandex_music.__version__ == "3.2.2"


def make_provider(gateway: FakeYandexGateway) -> YandexProvider:
    return YandexProvider(
        gateway, app_name="JustTheTwoOfUs", web_base="https://music.yandex.ru", clock=lambda: NOW
    )


@pytest.fixture
async def lib_gateway() -> AsyncIterator[LibraryYandexGateway]:
    async with httpx.AsyncClient() as http:
        yield LibraryYandexGateway(timeout_seconds=2, http=http)


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
    code = await provider.start_device_flow(user_key="user-1")
    assert gateway.device_names == ["JustTheTwoOfUs"]
    assert gateway.device_ids == [oauth_device_id("user-1")]
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


def test_music_app_credentials_come_from_the_pinned_library() -> None:
    client_id, client_secret = music_app_credentials()
    assert len(client_id) == 32
    assert len(client_secret) == 32


def test_oauth_device_id_is_stable_and_within_yandex_limits() -> None:
    device_id = oauth_device_id("user-1")
    assert device_id == oauth_device_id("user-1") != oauth_device_id("user-2")
    assert 6 <= len(device_id) <= 50
    assert device_id.isascii()
    assert device_id.isprintable()


@respx.mock
async def test_device_code_request(lib_gateway: LibraryYandexGateway) -> None:
    route = respx.post(f"{OAUTH_BASE}/device/code").mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dc",
                "user_code": "1234567",
                "verification_url": "https://ya.ru/device",
                "expires_in": 300,
                "interval": 5,
            },
        )
    )
    code = await lib_gateway.request_device_code(device_name="JustTheTwoOfUs", device_id="dev-1")
    form = parse_qs(route.calls.last.request.content.decode())
    assert form["client_id"] == [music_app_credentials()[0]]
    assert form["device_id"] == ["dev-1"]
    assert form["device_name"] == ["JustTheTwoOfUs"]
    assert "client_secret" not in form  # only the token request needs it
    assert (code.user_code, code.verification_url, code.expires_in, code.interval) == (
        "1234567",
        "https://ya.ru/device",
        300,
        5,
    )


@respx.mock
@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (httpx.Response(503), "provider_unreachable"),
        (httpx.Response(429), "provider_unreachable"),
        (httpx.Response(200, json={"device_code": "dc"}), "provider_bad_response"),
        (httpx.Response(200, text="<html>"), "provider_bad_response"),
        (httpx.Response(400, json={"error": "invalid_client"}), "provider_bad_response"),
    ],
)
async def test_device_code_failures(
    lib_gateway: LibraryYandexGateway, response: httpx.Response, error_code: str
) -> None:
    respx.post(f"{OAUTH_BASE}/device/code").mock(return_value=response)
    with pytest.raises(ProviderError) as excinfo:
        await lib_gateway.request_device_code(device_name="x", device_id="dev-1")
    assert excinfo.value.code == error_code


@respx.mock
async def test_device_code_network_error(lib_gateway: LibraryYandexGateway) -> None:
    respx.post(f"{OAUTH_BASE}/device/code").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(ProviderError) as excinfo:
        await lib_gateway.request_device_code(device_name="x", device_id="dev-1")
    assert excinfo.value.code == "provider_unreachable"


@respx.mock
async def test_device_token_success_and_pending(lib_gateway: LibraryYandexGateway) -> None:
    route = respx.post(f"{OAUTH_BASE}/token").mock(
        side_effect=[
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(
                200, json={"access_token": "tok", "expires_in": 100, "token_type": "bearer"}
            ),
        ]
    )
    assert await lib_gateway.poll_device_token("dc") is None
    assert await lib_gateway.poll_device_token("dc") == YandexToken("tok", 100)
    form = parse_qs(route.calls.last.request.content.decode())
    client_id, client_secret = music_app_credentials()
    assert form == {
        "grant_type": ["device_code"],
        "code": ["dc"],
        "client_id": [client_id],
        "client_secret": [client_secret],
    }


@respx.mock
@pytest.mark.parametrize(
    ("response", "expected", "detail"),
    [
        (httpx.Response(400, json={"error": "slow_down"}), DeviceFlowPending, "slow_down"),
        (httpx.Response(400, json={"error": "expired_token"}), DeviceFlowError, "expired"),
        (httpx.Response(400, json={"error": "invalid_grant"}), DeviceFlowError, "expired"),
        (httpx.Response(400, json={"error": "access_denied"}), DeviceFlowError, "denied"),
        (httpx.Response(400, json={"error": "invalid_client"}), DeviceFlowError, "failed"),
        (httpx.Response(400, text="not json"), DeviceFlowError, "failed"),
        (httpx.Response(502), ProviderError, "provider_unreachable"),
        (
            httpx.Response(200, json={"token_type": "bearer"}),
            ProviderError,
            "provider_bad_response",
        ),
    ],
)
async def test_device_token_error_mapping(
    lib_gateway: LibraryYandexGateway,
    response: httpx.Response,
    expected: type[Exception],
    detail: str,
) -> None:
    respx.post(f"{OAUTH_BASE}/token").mock(return_value=response)
    with pytest.raises(expected) as excinfo:
        await lib_gateway.poll_device_token("dc")
    error = excinfo.value
    if isinstance(error, DeviceFlowPending):
        assert error.slow_down
    elif isinstance(error, DeviceFlowError | ProviderError):
        assert error.code == detail


@respx.mock
async def test_revoke_token(lib_gateway: LibraryYandexGateway) -> None:
    route = respx.post(f"{OAUTH_BASE}/revoke_token").mock(
        side_effect=[
            httpx.Response(200, json={"status": "ok"}),
            httpx.Response(400, json={"error": "unsupported_token_type"}),
            httpx.ConnectError("down"),
        ]
    )
    assert await lib_gateway.revoke_token("tok") is True
    form = parse_qs(route.calls[0].request.content.decode())
    assert form["access_token"] == ["tok"]
    assert form["client_id"] == [music_app_credentials()[0]]
    assert await lib_gateway.revoke_token("tok") is False
    assert await lib_gateway.revoke_token("tok") is False


def test_ynison_client_points_at_the_local_fake_only_when_overridden() -> None:
    from yandex_music.ynison import YnisonClientAsync

    assert _ynison_client_class(None) is YnisonClientAsync
    fake = _ynison_client_class("http://127.0.0.1:8300")
    assert issubclass(fake, YnisonClientAsync)
    client = fake("tok", device_id="abcdef123456")
    assert client._redirect_uri().startswith("ws://127.0.0.1:8300/yandex/ynison/")

    class Redirect:
        host = "127.0.0.1:8300/yandex/ynison-state"

    assert client._state_uri(Redirect()).startswith("ws://127.0.0.1:8300/yandex/ynison-state/")


async def test_overridden_gateway_targets_the_fake() -> None:
    async with httpx.AsyncClient() as http:
        gateway = LibraryYandexGateway(
            timeout_seconds=2, http=http, upstream_override="http://127.0.0.1:8300"
        )
        with respx.mock:
            route = respx.post("http://127.0.0.1:8300/yandex/oauth/revoke_token").mock(
                return_value=httpx.Response(200, json={"status": "ok"})
            )
            assert await gateway.revoke_token("tok") is True
            assert route.called


async def test_library_gateway_maps_ynison_unauthorized(
    monkeypatch: pytest.MonkeyPatch, lib_gateway: LibraryYandexGateway
) -> None:
    from contextlib import asynccontextmanager

    from yandex_music.ynison import YnisonClientAsync

    @asynccontextmanager
    async def fake_session(self: Any, timeout: float = 10.0) -> Any:
        raise YnisonUnauthorizedError(message="bad token", http_code=401)
        yield self  # pragma: no cover

    monkeypatch.setattr(YnisonClientAsync, "session", fake_session)
    with pytest.raises(ProviderError) as excinfo:
        await lib_gateway.fetch_player_state(
            "tok", device_id="abcdef123456", device_title="JustTheTwoOfUs (read-only)"
        )
    assert excinfo.value.reauth_required


async def test_library_gateway_fetch_track_with_real_models(
    monkeypatch: pytest.MonkeyPatch, lib_gateway: LibraryYandexGateway
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
    meta = await lib_gateway.fetch_track("tok", "10994777")
    assert seen == [("tok", ["10994777"])]
    assert meta == YandexTrackMeta(
        title="Real Song",
        artist_names=("Singer",),
        album_title="Real Album",
        album_id="1193829",
        cover_uri="avatars.yandex.net/a/%%",  # falls back to the album cover
        duration_ms=180_000,
    )


async def test_library_gateway_fetch_track_errors(
    monkeypatch: pytest.MonkeyPatch, lib_gateway: LibraryYandexGateway
) -> None:
    from yandex_music.exceptions import UnauthorizedError

    async def unauthorized(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise UnauthorizedError("bad token")

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", unauthorized)
    with pytest.raises(ProviderError) as excinfo:
        await lib_gateway.fetch_track("tok", "1")
    assert excinfo.value.reauth_required

    async def flaky(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NetworkError("down")

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", flaky)
    assert await lib_gateway.fetch_track("tok", "1") is None

    async def empty(self: Any, *args: Any, **kwargs: Any) -> Any:
        return []

    monkeypatch.setattr(yandex_music.ClientAsync, "tracks", empty)
    assert await lib_gateway.fetch_track("tok", "1") is None


async def test_library_gateway_reads_state_through_a_session(
    monkeypatch: pytest.MonkeyPatch, lib_gateway: LibraryYandexGateway
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
    snapshot = await lib_gateway.fetch_player_state(
        "tok", device_id="abcdef123456", device_title="JustTheTwoOfUs (read-only)"
    )
    assert snapshot.playable is not None
    assert snapshot.playable.playable_id == "10994777"
    assert created == [
        {
            "device_id": "abcdef123456",
            "device_title": "JustTheTwoOfUs (read-only)",
            "max_reconnect_attempts": 1,
        }
    ]

    for error, code, retry in (
        (
            YnisonServerError(message="go away", http_code=429, go_away_seconds=60),
            "provider_rate_limited",
            60.0,
        ),
        (
            YnisonServerError(message="unavailable", http_code=503, go_away_seconds=3600),
            "provider_unreachable",
            3600.0,
        ),
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
            await lib_gateway.fetch_player_state(
                "tok", device_id="abcdef123456", device_title="t (read-only)"
            )
        assert (excinfo.value.code, excinfo.value.retry_after_seconds) == (code, retry)


def test_snapshot_rejects_an_unexpected_state_object() -> None:
    # If the unofficial library ever hands back something else, say so; never guess.
    with pytest.raises(ProviderError) as excinfo:
        snapshot_from_ynison_state(object(), now_ms=0)
    assert excinfo.value.code == "provider_bad_response"


# ----- recent songs (listening history) ------------------------------------------------


def _history_json() -> dict[str, Any]:
    def track(track_id: str, album_id: str, title: str) -> dict[str, Any]:
        return {
            "type": "track",
            "data": {
                "itemId": {"trackId": track_id, "albumId": album_id},
                "fullModel": {
                    "id": track_id,
                    "title": title,
                    "artists": [{"id": 1, "name": "Singer"}],
                    "albums": [
                        {
                            "id": int(album_id),
                            "title": "Album",
                            "coverUri": "avatars.yandex.net/get-music-content/1/a/%%",
                        }
                    ],
                },
            },
        }

    return {
        "historyTabs": [
            {
                "date": "2026-10-26",
                "items": [
                    {
                        "context": {"type": "album", "data": {"itemId": {"id": "456"}}},
                        "tracks": [
                            track("111", "456", "Newest"),
                            track("111", "456", "Newest"),  # played twice
                            # beyond fullModelsCount: no details, so skipped
                            {"type": "track", "data": {"itemId": {"trackId": "2", "albumId": "4"}}},
                        ],
                    }
                ],
            },
            {"date": "2026-10-25", "items": [{"tracks": [track("333", "789", "Yesterday")]}]},
        ]
    }


def test_history_tracks_from_real_library_models() -> None:
    history = yandex_music.MusicHistory.de_json(_history_json(), yandex_music.ClientAsync("tok"))
    tracks = history_tracks(history, limit=5)
    assert [(t.track_id, t.title, t.day) for t in tracks] == [
        ("111", "Newest", date(2026, 10, 26)),
        ("333", "Yesterday", date(2026, 10, 25)),
    ]
    assert tracks[0].album_id == "456"
    assert tracks[0].artist_names == ("Singer",)
    assert tracks[0].cover_uri == "avatars.yandex.net/get-music-content/1/a/%%"
    assert history_tracks(history, limit=1) == tracks[:1]
    assert history_tracks(None, limit=5) == ()
    with pytest.raises(ProviderError):
        history_tracks(object(), limit=5)


async def test_recent_songs_get_links_and_small_covers() -> None:
    gateway = FakeYandexGateway(
        history=(
            YandexHistoryTrack(
                "111",
                "456",
                "Song",
                ("Singer",),
                "avatars.yandex.net/get-music-content/1/a/%%",
                date(2026, 10, 26),
            ),
            YandexHistoryTrack("222", None, "No album", (), None, None),
        )
    )
    provider = make_provider(gateway)
    result = await provider.fetch_recent(Credentials("tok", None, None), subject_key="x", limit=5)
    first, second = result.tracks
    assert first.key == "111"
    assert first.track_url == "https://music.yandex.ru/album/456/track/111"
    assert first.artwork_url == "https://avatars.yandex.net/get-music-content/1/a/200x200"
    assert first.played_on == date(2026, 10, 26)
    assert first.played_at is None
    assert second.track_url is None
    assert second.artwork_url is None
    assert result.new_tokens is None
    with pytest.raises(ProviderError) as excinfo:
        await provider.fetch_recent(Credentials(None, None, None), subject_key="x", limit=5)
    assert excinfo.value.reauth_required


async def test_library_gateway_fetch_history(
    monkeypatch: pytest.MonkeyPatch, lib_gateway: LibraryYandexGateway
) -> None:
    seen: list[Any] = []

    async def fake_history(self: Any, full_models_count: int = 0, *args: Any, **kwargs: Any) -> Any:
        seen.append((self.token, full_models_count))
        return yandex_music.MusicHistory.de_json(_history_json(), self)

    monkeypatch.setattr(yandex_music.ClientAsync, "music_history", fake_history)
    tracks = await lib_gateway.fetch_history("tok", limit=5)
    assert seen == [("tok", 10)]
    assert [t.track_id for t in tracks] == ["111", "333"]

    async def flaky(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise NetworkError("down")

    monkeypatch.setattr(yandex_music.ClientAsync, "music_history", flaky)
    with pytest.raises(ProviderError) as excinfo:
        await lib_gateway.fetch_history("tok", limit=5)
    assert excinfo.value.code == "provider_unreachable"
