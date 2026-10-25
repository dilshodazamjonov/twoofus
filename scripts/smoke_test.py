"""HTTP part of scripts/smoke.sh. Drives the real app through the Next.js proxy.

Run via scripts/smoke.sh (which starts isolated servers). Uses only the DEMO
provider; Spotify is exercised up to the authorize URL and the callback's
state/session checks, without contacting Spotify.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

RESULTS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        print(f"FAIL {name} {detail}".rstrip())
        sys.exit(1)
    RESULTS.append(name)
    print(f"PASS {name}")


class Browser:
    """One cookie jar, like one browser profile."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.http = httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=30)

    def csrf(self) -> str:
        token = self.http.cookies.get("twoofus_csrf")
        if token is None:
            token = self.http.get("/api/v1/auth/csrf").json()["csrf_token"]
        return str(token)

    def send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if method != "GET":
            headers.setdefault("X-CSRF-Token", self.csrf())
        return self.http.request(method, path, headers=headers, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--backend", required=True)
    args = parser.parse_args()
    origin: str = args.origin
    backend: str = args.backend
    owner_password = os.environ["SMOKE_OWNER_PASSWORD"]

    a = Browser(origin)  # the owner's browser
    b = Browser(origin)  # the partner's browser

    health = a.http.get("/api/v1/health")
    check(
        "proxy: GET /api/v1/health", health.status_code == 200 and health.json() == {"status": "ok"}
    )
    ready = a.http.get("/api/v1/ready").json()
    check(
        "proxy: database migrated",
        ready == {"status": "ready", "database": "ok", "migrations": "ok"},
    )
    config = a.http.get("/api/v1/config").json()
    check(
        "config: demo enabled, yandex disabled",
        config["providers"]["demo"]["available"] and not config["providers"]["yandex"]["available"],
    )
    direct = httpx.get(f"{backend}/api/v1/config", timeout=10)
    check(
        "API refuses requests that bypass the proxy (no proxy secret)",
        direct.status_code == 403 and direct.json()["error"]["code"] == "proxy_required",
    )
    forged = httpx.get(
        f"{backend}/api/v1/config", headers={"X-TwoOfUs-Proxy-Auth": "guessed"}, timeout=10
    )
    check("API refuses a guessed proxy secret", forged.status_code == 403)
    check(
        "setup status: the owner exists",
        a.http.get("/api/v1/setup/status").json() == {"owner_exists": True},
    )

    refused = a.http.post(
        "/api/v1/auth/login", json={"username": "smokeowner", "password": owner_password}
    )
    check("CSRF: login without token is refused", refused.status_code == 403)

    login = a.send(
        "POST", "/api/v1/auth/login", json={"username": "smokeowner", "password": owner_password}
    )
    check(
        "login through proxy", login.status_code == 200 and login.json()["user"]["role"] == "owner"
    )
    set_cookies = login.headers.get_list("set-cookie")
    session_cookie = next((c for c in set_cookies if c.startswith("twoofus_session=")), "")
    check(
        "session cookie forwarded by proxy: HttpOnly + SameSite=Lax",
        "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie,
    )
    check("security headers survive the proxy", login.headers.get("cache-control") == "no-store")

    session = a.http.get("/api/v1/auth/session").json()
    check("session is authenticated", session["authenticated"] is True)

    big = a.send("POST", "/api/v1/auth/login", content=b"x" * (70 * 1024))
    check("oversized request body is refused (413)", big.status_code == 413)

    demo = a.send("POST", "/api/v1/providers/demo/connect")
    check("connect DEMO provider", demo.status_code == 200 and demo.json()["provider"] == "demo")
    view = a.http.get("/api/v1/room/now-playing").json()
    me = view["me"]["playback"]
    check(
        "now-playing: own DEMO playback, labelled",
        me["source"] == "demo"
        and me["is_demo"] is True
        and me["status"] in {"playing", "paused", "idle"},
    )
    print(f"     demo says: {me['status']} - {me['track_title']} / {', '.join(me['artist_names'])}")

    invite = a.send("POST", "/api/v1/invitations")
    check("owner creates invitation", invite.status_code == 201)
    token = invite.json()["token"]
    check(
        "invite link keeps the token in the URL fragment",
        invite.json()["invite_url"].startswith(f"{origin}/invite#token="),
    )
    inspect = b.send("POST", "/api/v1/invitations/inspect", json={"token": token})
    check(
        "partner inspects invitation",
        inspect.status_code == 200 and inspect.json()["inviter_display_name"] == "Smoke Owner",
    )
    accept = b.send(
        "POST",
        "/api/v1/invitations/accept",
        json={
            "token": token,
            "username": "smokepartner",
            "display_name": "Smoke Partner",
            "password": owner_password + "-p",
        },
    )
    check(
        "partner accepts and is signed in",
        accept.status_code == 201 and accept.json()["user"]["role"] == "partner",
    )
    reuse = Browser(origin).send(
        "POST",
        "/api/v1/invitations/accept",
        json={
            "token": token,
            "username": "third",
            "display_name": "T",
            "password": "another-password-1",
        },
    )
    check("invitation is single-use", reuse.status_code == 400)

    hidden = b.http.get("/api/v1/room/now-playing").json()["partner"]["playback"]
    check(
        "consent: owner not sharing -> partner sees 'private' only",
        hidden["status"] == "private"
        and hidden["track_title"] is None
        and hidden["source"] is None,
    )
    share = a.send(
        "PUT",
        "/api/v1/me/sharing",
        json={
            "share_now_playing": True,
            "acknowledged_notice_version": config["sharing_notice_version"],
        },
    )
    check("owner turns sharing on (notice acknowledged)", share.status_code == 200)
    visible = b.http.get("/api/v1/room/now-playing").json()["partner"]["playback"]
    check(
        "consent: partner now sees owner's DEMO playback",
        visible["source"] == "demo" and visible["is_demo"] is True,
    )
    a.send("PUT", "/api/v1/me/sharing", json={"share_now_playing": False})
    again = b.http.get("/api/v1/room/now-playing").json()["partner"]["playback"]
    check("consent: turning sharing off hides it immediately", again["status"] == "private")

    authorize = a.send("POST", "/api/v1/providers/spotify/authorize")
    url = authorize.json()["authorization_url"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    check(
        "Spotify authorize URL: PKCE S256, minimal scope, exact redirect",
        url.startswith("https://accounts.spotify.com/authorize?")
        and query["code_challenge_method"] == "S256"
        and query["scope"] == "user-read-currently-playing"
        and query["redirect_uri"] == f"{origin}/api/v1/providers/spotify/callback",
    )
    hijack = b.http.get(
        "/api/v1/providers/spotify/callback", params={"state": query["state"], "code": "x"}
    )
    check(
        "callback via proxy: other person's session is refused",
        hijack.status_code == 303
        and hijack.headers["location"] == "/connect?connect=spotify&result=session_mismatch",
    )
    url = a.send("POST", "/api/v1/providers/spotify/authorize").json()["authorization_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    denied = a.http.get(
        "/api/v1/providers/spotify/callback", params={"state": state, "error": "access_denied"}
    )
    check(
        "callback via proxy: session cookie arrives, state accepted, denial reported",
        denied.headers["location"] == "/connect?connect=spotify&result=access_denied",
    )
    landing = a.http.get(denied.headers["location"])
    check(
        "redirect target page renders",
        landing.status_code == 200 and "JustTheTwoOfUs" in landing.text,
    )

    bodies = "".join(
        client.http.get(path).text
        for client in (a, b)
        for path in (
            "/api/v1/room",
            "/api/v1/room/now-playing",
            "/api/v1/providers",
            "/api/v1/auth/session",
        )
    )
    check(
        "no invite token or password in any response",
        token not in bodies and owner_password not in bodies,
    )

    logout = a.send("POST", "/api/v1/auth/logout")
    check("logout", logout.status_code == 200)
    check("after logout: 401", a.http.get("/api/v1/me").status_code == 401)

    wrong = b.send("DELETE", "/api/v1/me", json={"password": "not-my-password"})
    check(
        "account deletion needs the password (DELETE body passes the proxy)",
        wrong.status_code == 403,
    )
    gone = b.send("DELETE", "/api/v1/me", json={"password": owner_password + "-p"})
    check("partner deletes own account", gone.status_code == 204)
    check("deleted account is signed out", b.http.get("/api/v1/me").status_code == 401)

    # A client-supplied X-Forwarded-For must not reach the per-IP rate limiter.
    probe = Browser(origin)
    for i in range(21):
        probe.send(
            "POST",
            "/api/v1/auth/login",
            json={"username": f"nobody{i}", "password": "wrong-password-x"},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
    other = probe.send(
        "POST",
        "/api/v1/auth/login",
        json={"username": "nobody-x", "password": "wrong-password-x"},
        headers={"X-Forwarded-For": "203.0.113.8"},
    )
    check(
        "client-supplied X-Forwarded-For is ignored by the per-IP rate limit",
        other.status_code == 429,
        f"(got {other.status_code})",
    )

    print(f"\nSmoke test passed: {len(RESULTS)} checks.")


if __name__ == "__main__":
    main()
