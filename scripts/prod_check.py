"""HTTP checks for scripts/prod-check.sh, against the real production stack.

Everything goes through Caddy on https://127.0.0.1:8443 (Caddy's internal test
CA, verified with --cacert), except the checks that prove what must NOT be
reachable, which run inside the stack's containers with `docker compose exec`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

DEPLOY_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "deploy", "scripts")
RESULTS: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        print(f"FAIL {name} {detail}".rstrip())
        sys.exit(1)
    RESULTS.append(name)
    print(f"PASS {name}")


class Browser:
    def __init__(self, origin: str, cacert: str) -> None:
        self.origin = origin
        self.http = httpx.Client(
            base_url=origin, headers={"Origin": origin}, verify=cacert, timeout=30
        )

    def csrf(self) -> str:
        for cookie in self.http.cookies.jar:
            if cookie.name == "__Host-twoofus_csrf":
                return str(cookie.value)
        return str(self.http.get("/api/v1/auth/csrf").json()["csrf_token"])

    def send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        if method != "GET":
            headers.setdefault("X-CSRF-Token", self.csrf())
        return self.http.request(method, path, headers=headers, **kwargs)


class Stack:
    def __init__(self, project: str, compose_file: str) -> None:
        self.base = ["docker", "compose", "-p", project, "-f", compose_file]

    def run(self, *args: str, check_ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(  # noqa: S603 - fixed docker compose invocations
            [*self.base, *args], capture_output=True, text=True, timeout=180, check=False
        )
        if check_ok and result.returncode != 0:
            print(result.stdout, result.stderr)
        return result

    def node(self, service: str, script: str) -> str:
        return self.run("exec", "-T", service, "node", "-e", script, check_ok=False).stdout.strip()

    def python(self, script: str) -> str:
        return self.run("exec", "-T", "api", "python", "-c", script, check_ok=False).stdout.strip()


def cookie_lines(response: httpx.Response) -> dict[str, str]:
    lines = {}
    for line in response.headers.get_list("set-cookie"):
        lines[line.split("=", 1)[0]] = line
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--http", required=True)
    parser.add_argument("--cacert", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose-file", required=True)
    args = parser.parse_args()
    origin: str = args.origin
    owner_password = os.environ["OWNER_PASSWORD"]
    stack = Stack(args.project, args.compose_file)

    # ----- TLS edge, redirects, headers ------------------------------------------------
    plain = httpx.get(f"{args.http}/room", follow_redirects=False, timeout=10)
    check(
        "plain HTTP is redirected to HTTPS",
        plain.status_code in (301, 308) and plain.headers["location"].startswith("https://"),
    )
    a = Browser(origin, args.cacert)
    page = a.http.get("/sign-in")
    h = page.headers
    check("page served over HTTPS", page.status_code == 200 and page.url.scheme == "https")
    check(
        "HSTS on every response",
        h.get("strict-transport-security", "").startswith("max-age=63072000"),
    )
    csp = h.get("content-security-policy", "")
    nonce = re.search(r"'nonce-([A-Za-z0-9+/=]+)'", csp)
    check(
        "strict CSP with a per-request nonce",
        nonce is not None
        and "'strict-dynamic'" in csp
        and "'unsafe-eval'" not in csp
        and "frame-ancestors 'none'" in csp,
    )
    scripts = re.findall(r"<script\b[^>]*>", page.text)
    check(
        "every script tag carries this response's nonce",
        bool(scripts) and all(f'nonce="{nonce.group(1)}"' in s for s in scripts if nonce),
        f"({len(scripts)} scripts)",
    )
    check(
        "nonce changes per request",
        a.http.get("/sign-in").headers.get("content-security-policy") != csp,
    )
    check(
        "frame, sniffing, referrer, permissions, COOP headers",
        h.get("x-frame-options") == "DENY"
        and h.get("x-content-type-options") == "nosniff"
        and h.get("referrer-policy") == "no-referrer"
        and "camera=()" in h.get("permissions-policy", "")
        and h.get("cross-origin-opener-policy") == "same-origin",
    )
    check(
        "no server banners",
        "server" not in h and "x-powered-by" not in h and "via" not in h,
        f"(server={h.get('server')!r}, via={h.get('via')!r})",
    )

    # ----- production API surface ----------------------------------------------------------
    ready = a.http.get("/api/v1/ready").json()
    check(
        "ready: database and migrations",
        ready == {"status": "ready", "database": "ok", "migrations": "ok"},
    )
    config = a.http.get("/api/v1/config").json()
    check(
        "production config: no demo anywhere",
        config["environment"] == "production"
        and config["demo_mode"] is False
        and config["demo_controls"] is False
        and config["providers"]["demo"]["available"] is False,
    )
    check("API docs are off in production", a.http.get("/api/v1/docs").status_code == 404)
    check(
        "OpenAPI document is off in production",
        a.http.get("/api/v1/openapi.json").status_code == 404,
    )
    api_headers = a.http.get("/api/v1/health").headers
    check(
        "API responses: no-store and deny-all CSP",
        api_headers.get("cache-control") == "no-store"
        and api_headers.get("content-security-policy")
        == "default-src 'none'; frame-ancestors 'none'",
    )
    manifest = a.http.get("/manifest.webmanifest")
    check(
        "manifest is served and named by the API (server-side call carries the proxy secret)",
        manifest.status_code == 200 and manifest.json()["name"] == "JustTheTwoOfUs",
    )
    sw = a.http.get("/sw.js")
    check(
        "service worker script is never cached by the browser",
        sw.status_code == 200 and "no-store" in sw.headers.get("cache-control", ""),
    )
    check("demo artwork is not in the image", a.http.get("/demo/cover-1.svg").status_code == 404)

    # ----- sessions and cookies -------------------------------------------------------------
    login = a.send(
        "POST", "/api/v1/auth/login", json={"username": "owner", "password": owner_password}
    )
    check("owner signs in through the proxy", login.status_code == 200)
    cookies = cookie_lines(login)
    session_cookie = cookies.get("__Host-twoofus_session", "")
    check(
        "session cookie: __Host- prefix, Secure, HttpOnly, SameSite=Lax, Path=/, no Domain",
        "Secure" in session_cookie
        and "HttpOnly" in session_cookie
        and "SameSite=lax" in session_cookie
        and "Path=/" in session_cookie
        and "Domain" not in session_cookie,
        f"({session_cookie.split(';', 1)[-1].strip()})",
    )
    check(
        "CSRF cookie: __Host- prefix and Secure",
        "Secure" in cookies.get("__Host-twoofus_csrf", ""),
    )
    no_csrf = a.http.put("/api/v1/me/sharing", json={"share_now_playing": False})
    check(
        "writes without the CSRF token are refused",
        no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "csrf_failed",
        f"({no_csrf.status_code})",
    )
    cross_origin = a.http.put(
        "/api/v1/me/sharing",
        json={"share_now_playing": False},
        headers={"Origin": "https://evil.example", "X-CSRF-Token": a.csrf()},
    )
    check("writes from another origin are refused", cross_origin.status_code == 403)

    # ----- the authenticated proxy hop and network isolation ----------------------------------
    direct = stack.node(
        "web",
        "fetch('http://api:8000/api/v1/config')"
        ".then(r => console.log(r.status), e => console.log('ERR'))",
    )
    check(
        "inside the stack, the API refuses requests without the proxy secret",
        direct == "403",
        direct,
    )
    guessed = stack.node(
        "web",
        "fetch('http://api:8000/api/v1/config',{headers:{'x-twoofus-proxy-auth':'guess'}})"
        ".then(r => console.log(r.status), e => console.log('ERR'))",
    )
    check("a guessed proxy secret is refused", guessed == "403", guessed)
    exposed = {}
    for service in ("api", "web", "db"):
        container = stack.run("ps", "-q", service).stdout.strip()
        exposed[service] = subprocess.run(  # noqa: S603
            ["docker", "inspect", container, "--format", "{{json .HostConfig.PortBindings}}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    check(
        "only Caddy publishes ports: api, web and db have none",
        all(value in ("{}", "null") for value in exposed.values()),
        str(exposed),
    )
    web_egress = stack.node(
        "web",
        "require('net').connect({host:'1.1.1.1',port:443,timeout:3000})"
        ".on('connect',()=>{console.log('OPEN');process.exit(0)})"
        ".on('error',()=>{console.log('BLOCKED');process.exit(0)})"
        ".on('timeout',()=>{console.log('BLOCKED');process.exit(0)})",
    )
    check("the web container has no route to the internet", web_egress == "BLOCKED", web_egress)
    db_reach = stack.node(
        "web",
        "require('net').connect({host:'db',port:5432,timeout:3000})"
        ".on('connect',()=>{console.log('OPEN');process.exit(0)})"
        ".on('error',()=>{console.log('BLOCKED');process.exit(0)})"
        ".on('timeout',()=>{console.log('BLOCKED');process.exit(0)})",
    )
    check("the web container cannot reach the database", db_reach == "BLOCKED", db_reach)
    api_egress = stack.python(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('accounts.spotify.com', 443), 5).close(); print('OPEN')\n"
        "except OSError:\n"
        "    print('BLOCKED')"
    )
    if api_egress == "OPEN":
        check("the API can reach the music services (egress network)", True)
    else:
        print("INFO the API could not reach accounts.spotify.com (offline machine?); not checked")

    # ----- client IP, limits ------------------------------------------------------------------
    probe = Browser(origin, args.cacert)
    statuses = []
    for i in range(21):
        statuses.append(
            probe.send(
                "POST",
                "/api/v1/auth/login",
                json={"username": f"nobody{i}", "password": "wrong-password-x"},
                headers={"X-Forwarded-For": f"203.0.113.{i}"},
            ).status_code
        )
    check(
        "spoofed X-Forwarded-For does not dodge the per-IP login limit",
        statuses[-1] == 429,
        f"(last statuses {statuses[-3:]})",
    )
    big = a.send("POST", "/api/v1/auth/login", content=b"x" * (70 * 1024))
    check("oversized bodies are refused at the edge", big.status_code == 413)

    # ----- the two-person flow, as deployed ----------------------------------------------------
    b = Browser(origin, args.cacert)
    invite = a.send("POST", "/api/v1/invitations")
    check(
        "invitation link uses the public HTTPS origin and keeps the token in the fragment",
        invite.status_code == 201
        and invite.json()["invite_url"].startswith(f"{origin}/invite#token="),
    )
    token = invite.json()["token"]
    accept = b.send(
        "POST",
        "/api/v1/invitations/accept",
        json={
            "token": token,
            "username": "partner",
            "display_name": "Partner",
            "password": owner_password + "-p",
        },
    )
    check("partner accepts the invitation", accept.status_code == 201)
    hidden = b.http.get("/api/v1/room/now-playing").json()["partner"]["playback"]
    check(
        "not sharing: the partner sees nothing",
        hidden["status"] == "private" and hidden["source"] is None,
    )
    check(
        "Demo cannot be connected in production",
        a.send("POST", "/api/v1/providers/demo/connect").status_code in (404, 503),
    )

    # ----- Spotify callback through the proxy (Spotify itself is not contacted) ---------------
    authorize = a.send("POST", "/api/v1/providers/spotify/authorize").json()["authorization_url"]
    query = parse_qs(urlsplit(authorize).query)
    check(
        "Spotify redirect URI is the public HTTPS origin",
        query["redirect_uri"] == [f"{origin}/api/v1/providers/spotify/callback"],
    )
    hijack = b.http.get(
        "/api/v1/providers/spotify/callback", params={"state": query["state"][0], "code": "x"}
    )
    check(
        "callback in another person's session is refused (relative redirect)",
        hijack.status_code == 303
        and hijack.headers["location"] == "/connect?connect=spotify&result=session_mismatch",
    )
    state = parse_qs(
        urlsplit(
            a.send("POST", "/api/v1/providers/spotify/authorize").json()["authorization_url"]
        ).query
    )["state"][0]
    denied = a.http.get(
        "/api/v1/providers/spotify/callback", params={"state": state, "error": "access_denied"}
    )
    check(
        "callback with the session cookie over HTTPS: state accepted",
        denied.headers.get("location") == "/connect?connect=spotify&result=access_denied",
    )

    # ----- restart: sessions live in PostgreSQL, not in memory ---------------------------------
    stack.run("restart", "api")
    for _ in range(60):
        try:
            if a.http.get("/api/v1/ready").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    check(
        "after an API restart both people are still signed in",
        a.http.get("/api/v1/me").status_code == 200 and b.http.get("/api/v1/me").status_code == 200,
    )

    # ----- backup and restore ----------------------------------------------------------------
    renamed = a.send("PATCH", "/api/v1/me", json={"display_name": "Before Backup"})
    check("profile change before the backup", renamed.status_code == 200)
    backup = subprocess.run(  # noqa: S603
        [os.path.join(DEPLOY_SCRIPTS, "backup.sh")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "COMPOSE_PROJECT_NAME": args.project},
    )
    check(
        "backup.sh writes a dump",
        backup.returncode == 0 and "backup written" in backup.stdout,
        backup.stderr,
    )
    dump = backup.stdout.split("backup written: ")[1].split(" (")[0]
    check(
        "the dump is a file backup.sh named",
        re.fullmatch(r"/[\w./-]+/twoofus-\d{8}T\d{6}Z\.dump", dump) is not None,
        dump,
    )
    a.send("PATCH", "/api/v1/me", json={"display_name": "After Backup"})
    restore = subprocess.run(  # noqa: S603
        # argv list, no shell; `dump` was validated above.
        [os.path.join(DEPLOY_SCRIPTS, "restore.sh"), dump],  # nosemgrep
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env={
            **os.environ,
            "COMPOSE_PROJECT_NAME": args.project,
            "TWOOFUS_RESTORE_CONFIRM": "restore",
        },
    )
    check("restore.sh restores the dump", restore.returncode == 0, restore.stderr[-500:])
    for _ in range(60):
        try:
            if a.http.get("/api/v1/ready").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    check(
        "restored data is the backup's (and sessions survive)",
        a.http.get("/api/v1/me").json().get("display_name") == "Before Backup",
    )

    # ----- account deletion as deployed ---------------------------------------------------------
    gone = b.send("DELETE", "/api/v1/me", json={"password": owner_password + "-p"})
    check("the partner can delete their account", gone.status_code == 204)
    check("the deleted partner is signed out", b.http.get("/api/v1/me").status_code == 401)
    a.send("PATCH", "/api/v1/me", json={"display_name": "Owner"})

    print(f"\nProduction-stack HTTP checks passed: {len(RESULTS)}.")


if __name__ == "__main__":
    main()
