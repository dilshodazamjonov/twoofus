"""Managing one's own sessions: list, sign out elsewhere, no cross-user access."""

from __future__ import annotations

from typing import Any

from tests.conftest import OWNER_PASSWORD, ApiClient


async def test_list_and_revoke_other_sessions(owner_client: ApiClient, make_client: Any) -> None:
    phone: ApiClient = make_client()
    assert (await phone.login("khaled", OWNER_PASSWORD)).status_code == 200
    laptop: ApiClient = make_client()
    assert (await laptop.login("khaled", OWNER_PASSWORD)).status_code == 200

    listed = await owner_client.get("/api/v1/me/sessions")
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert len(sessions) == 3
    assert [s["current"] for s in sessions].count(True) == 1
    assert set(sessions[0]) == {"id", "created_at", "last_seen_at", "expires_at", "current"}

    # Sign out one specific other device...
    other = next(s for s in sessions if not s["current"])
    assert (await owner_client.delete(f"/api/v1/me/sessions/{other['id']}")).status_code == 204
    assert (await owner_client.delete(f"/api/v1/me/sessions/{other['id']}")).status_code == 404
    survivors = [(await c.get("/api/v1/me")).status_code for c in (phone, laptop)]
    assert sorted(survivors) == [200, 401]

    # ...then everywhere else.
    revoked = await owner_client.post("/api/v1/me/sessions/revoke-others")
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked": 1}
    assert (await phone.get("/api/v1/me")).status_code == 401
    assert (await laptop.get("/api/v1/me")).status_code == 401
    assert (await owner_client.get("/api/v1/me")).status_code == 200
    assert len((await owner_client.get("/api/v1/me/sessions")).json()["sessions"]) == 1


async def test_current_session_is_left_via_logout(owner_client: ApiClient) -> None:
    current = (await owner_client.get("/api/v1/me/sessions")).json()["sessions"][0]
    response = await owner_client.delete(f"/api/v1/me/sessions/{current['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "current_session"


async def test_cannot_see_or_revoke_the_partners_sessions(
    owner_client: ApiClient, partner_client: ApiClient
) -> None:
    theirs = (await partner_client.get("/api/v1/me/sessions")).json()["sessions"]
    mine = (await owner_client.get("/api/v1/me/sessions")).json()["sessions"]
    assert {s["id"] for s in theirs}.isdisjoint({s["id"] for s in mine})
    attempt = await owner_client.delete(f"/api/v1/me/sessions/{theirs[0]['id']}")
    assert attempt.status_code == 404  # same answer as a random id: no oracle
    assert (await partner_client.get("/api/v1/me")).status_code == 200
    random_id = await owner_client.delete(
        "/api/v1/me/sessions/00000000-0000-4000-8000-000000000000"
    )
    assert random_id.status_code == 404


async def test_session_endpoint_reports_and_clears_an_ended_session(
    owner_client: ApiClient, make_client: Any
) -> None:
    other: ApiClient = make_client()
    assert (await other.login("khaled", OWNER_PASSWORD)).status_code == 200
    await other.post("/api/v1/me/sessions/revoke-others")  # signs the owner_client out

    response = await owner_client.get("/api/v1/auth/session")
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["session_expired"] is True
    assert "twoofus_session" not in owner_client.http.cookies  # the stale cookie is cleared

    again = await owner_client.get("/api/v1/auth/session")
    assert again.json()["session_expired"] is False  # nothing left to report
    fresh: ApiClient = make_client()
    assert (await fresh.get("/api/v1/auth/session")).json()["session_expired"] is False
