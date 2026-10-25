"""Recent songs, picks, the shared playlist and the daily question: consent,
nothing typed is stored, limits, retention and account deletion."""

from __future__ import annotations

from typing import Any

import pytest
import respx
from sqlalchemy import func, select

from app.context import AppContext
from app.models import DailyAnswer, PlaylistItem, ProviderName, SongPick, User
from app.providers.base import TokenSet
from app.services import questions, songs
from app.services.maintenance import purge_expired
from app.services.provider_auth import store_connection
from tests.conftest import PARTNER_PASSWORD, ApiClient, FakeClock, enable_sharing

RECENT = "/api/v1/room/recent"
SONGS = "/api/v1/room/songs"
PICK = f"{SONGS}/pick"
PLAYLIST = f"{SONGS}/playlist"
QUESTION = "/api/v1/room/question"


async def connect_demo(*clients: ApiClient) -> None:
    for client in clients:
        assert (await client.post("/api/v1/providers/demo/connect")).status_code == 200


async def recent(client: ApiClient) -> dict[str, Any]:
    response = await client.get(RECENT)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def my_songs(client: ApiClient) -> list[dict[str, Any]]:
    body = await recent(client)
    assert body["me"]["state"] == "ok"
    tracks: list[dict[str, Any]] = body["me"]["tracks"]
    return tracks


async def count(ctx: AppContext, model: Any) -> int:
    async with ctx.session_factory() as db:
        return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


# ----- recent songs -------------------------------------------------------------------


async def test_recent_songs_follow_sharing(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    await connect_demo(owner_client, partner_client)
    body = await recent(owner_client)
    assert body["me"]["state"] == "ok"
    assert body["me"]["source"] == "demo"
    assert len({t["key"] for t in body["me"]["tracks"]}) == 5
    # Not shared with me: nothing about the partner's songs.
    assert body["partner"]["state"] == "private"
    assert body["partner"]["tracks"] == []
    assert body["partner"]["source"] is None

    await enable_sharing(partner_client)
    shared = await recent(owner_client)
    assert shared["partner"]["state"] == "ok"
    assert len(shared["partner"]["tracks"]) == 5


async def test_recent_without_a_connection_or_partner(owner_client: ApiClient) -> None:
    body = await recent(owner_client)
    assert body["me"]["state"] == "not_connected"
    assert body["partner"] is None


@respx.mock  # any request to Spotify would fail the test
async def test_an_older_spotify_grant_asks_for_permission(
    owner_client: ApiClient, ctx: AppContext, owner: User
) -> None:
    async with ctx.session_factory() as db:
        await store_connection(
            db,
            ctx,
            user_id=owner.id,
            provider=ProviderName.SPOTIFY,
            tokens=TokenSet("access-1", "refresh-1", None, "user-read-currently-playing"),
        )
        await db.commit()
    body = await recent(owner_client)
    assert body["me"]["state"] == "needs_permission"
    assert body["me"]["source"] == "spotify"


# ----- a song for the other member ----------------------------------------------------


async def test_pick_a_song_for_the_partner(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    await connect_demo(owner_client)
    first, second = (await my_songs(owner_client))[:2]
    picked = await owner_client.put(PICK, json={"key": first["key"]})
    assert picked.status_code == 200, picked.text
    assert picked.json()["from_me"]["title"] == first["title"]

    theirs = (await partner_client.get(SONGS)).json()
    assert theirs["for_me"]["title"] == first["title"]
    assert theirs["for_me"]["artist_names"] == first["artist_names"]
    assert theirs["for_me"]["artwork_url"] == first["artwork_url"]
    assert theirs["from_me"] is None

    # A new pick replaces the old one; taking it back clears it.
    await owner_client.put(PICK, json={"key": second["key"]})
    assert (await partner_client.get(SONGS)).json()["for_me"]["title"] == second["title"]
    cleared = await owner_client.delete(PICK)
    assert cleared.json()["from_me"] is None
    assert (await partner_client.get(SONGS)).json()["for_me"] is None


async def test_only_your_recent_songs_and_nothing_typed(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    await connect_demo(owner_client)
    unknown = await owner_client.put(PICK, json={"key": "demo-999"})
    assert unknown.status_code == 409
    assert unknown.json()["error"]["code"] == "song_not_recent"

    song = (await my_songs(owner_client))[0]
    injected = await owner_client.put(
        PICK, json={"key": song["key"], "title": "<script>", "track_url": "https://evil.example"}
    )
    assert injected.status_code == 422  # only the key is accepted
    assert (await owner_client.post(PLAYLIST, json={"key": "../../x"})).status_code == 422
    assert (await partner_client.get(SONGS)).json()["for_me"] is None


async def test_picking_needs_a_partner(owner_client: ApiClient) -> None:
    await connect_demo(owner_client)
    song = (await my_songs(owner_client))[0]
    alone = await owner_client.put(PICK, json={"key": song["key"]})
    assert alone.status_code == 409
    assert alone.json()["error"]["code"] == "no_partner"


# ----- the shared playlist ------------------------------------------------------------


async def test_shared_playlist(
    owner_client: ApiClient,
    partner_client: ApiClient,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await connect_demo(owner_client, partner_client)
    mine = await my_songs(owner_client)
    added = await owner_client.post(PLAYLIST, json={"key": mine[0]["key"]})
    assert added.status_code == 200, added.text
    again = await owner_client.post(PLAYLIST, json={"key": mine[0]["key"]})
    assert len(again.json()["playlist"]) == 1  # each song once

    clock.advance(seconds=5)
    other = next(t for t in await my_songs(partner_client) if t["key"] != mine[0]["key"])
    await partner_client.post(PLAYLIST, json={"key": other["key"]})
    listing = (await owner_client.get(SONGS)).json()["playlist"]
    assert [e["song"]["title"] for e in listing] == [other["title"], mine[0]["title"]]
    assert [e["added_by_me"] for e in listing] == [False, True]

    # Either member can remove any song; removing twice is harmless.
    removed = await partner_client.delete(f"{PLAYLIST}/{listing[1]['id']}")
    assert [e["song"]["title"] for e in removed.json()["playlist"]] == [other["title"]]
    assert (await partner_client.delete(f"{PLAYLIST}/{listing[1]['id']}")).status_code == 200

    monkeypatch.setattr(songs, "MAX_PLAYLIST", 2)
    fresh = [t for t in mine if t["key"] != other["key"]]
    await owner_client.post(PLAYLIST, json={"key": fresh[0]["key"]})
    full = await owner_client.post(PLAYLIST, json={"key": fresh[1]["key"]})
    assert full.status_code == 409
    assert full.json()["error"]["code"] == "playlist_full"


# ----- the question of the day --------------------------------------------------------


async def test_answers_are_revealed_once_both_answered(
    owner_client: ApiClient, partner_client: ApiClient, clock: FakeClock
) -> None:
    today = (await owner_client.get(QUESTION)).json()
    assert today["question"] == questions.question_for(clock.now.date())
    assert today["my_answer"] is None
    assert today["partner_answer"] is None

    answered = await partner_client.put(QUESTION, json={"answer": "  Paper   Lanterns "})
    assert answered.status_code == 200, answered.text
    assert answered.json()["my_answer"] == "Paper Lanterns"
    assert answered.json()["partner_answer"] is None
    # Not answered yet: the owner neither sees the answer nor learns it exists.
    assert (await owner_client.get(QUESTION)).json()["partner_answer"] is None

    mine = await owner_client.put(QUESTION, json={"answer": "Kettle Song"})
    assert mine.json()["partner_answer"] == "Paper Lanterns"
    assert (await partner_client.get(QUESTION)).json()["partner_answer"] == "Kettle Song"

    await owner_client.put(QUESTION, json={"answer": "Window Seat"})  # changed my mind
    assert (await partner_client.get(QUESTION)).json()["partner_answer"] == "Window Seat"

    clock.advance(days=1)
    tomorrow = (await owner_client.get(QUESTION)).json()
    assert tomorrow["question"] != today["question"]
    assert tomorrow["my_answer"] is None
    assert tomorrow["partner_answer"] is None


async def test_answer_validation(owner_client: ApiClient) -> None:
    for bad in ["   ", "x" * 141, "x" * 300, "line\x00break"]:
        response = await owner_client.put(QUESTION, json={"answer": bad})
        assert response.status_code == 422, bad


async def test_old_answers_are_deleted(
    owner_client: ApiClient, ctx: AppContext, clock: FakeClock
) -> None:
    await owner_client.put(QUESTION, json={"answer": "Something"})
    clock.advance(days=7)
    async with ctx.session_factory() as db:
        await purge_expired(db, clock)
    assert await count(ctx, DailyAnswer) == 1
    clock.advance(days=1)
    async with ctx.session_factory() as db:
        await purge_expired(db, clock)
    assert await count(ctx, DailyAnswer) == 0


# ----- access and account deletion ----------------------------------------------------


async def test_leaving_removes_their_songs_and_answers(
    owner_client: ApiClient, partner_client: ApiClient, ctx: AppContext
) -> None:
    await connect_demo(owner_client, partner_client)
    theirs = (await my_songs(partner_client))[0]
    assert (await partner_client.put(PICK, json={"key": theirs["key"]})).status_code == 200
    mine = (await my_songs(owner_client))[0]
    assert (await owner_client.put(PICK, json={"key": mine["key"]})).status_code == 200
    assert (await partner_client.post(PLAYLIST, json={"key": theirs["key"]})).status_code == 200
    assert (await partner_client.put(QUESTION, json={"answer": "Bye"})).status_code == 200

    deleted = await partner_client.delete("/api/v1/me", json={"password": PARTNER_PASSWORD})
    assert deleted.status_code == 204, deleted.text
    for model in (SongPick, PlaylistItem, DailyAnswer):
        assert await count(ctx, model) == 0, model


async def test_strangers_get_nothing(make_client: Any) -> None:
    stranger: ApiClient = make_client()
    for method, path in [
        ("GET", RECENT),
        ("GET", SONGS),
        ("PUT", PICK),
        ("POST", PLAYLIST),
        ("GET", QUESTION),
        ("PUT", QUESTION),
    ]:
        response = await stranger.request(method, path, json={"key": "x", "answer": "x"})
        assert response.status_code in (401, 422), (method, path, response.status_code)
        if response.status_code == 422:
            # Validation runs first for malformed bodies; a valid body still needs a session.
            ok_body = {"key": "x"} if path != QUESTION else {"answer": "x"}
            assert (await stranger.request(method, path, json=ok_body)).status_code == 401
