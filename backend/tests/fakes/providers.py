"""A local stand-in for Spotify and Yandex, for tests only.

It speaks the same wire formats the real adapters use, so the backend's real
provider code (httpx for Spotify and Yandex ID OAuth, the yandex-music
library's Ynison WebSocket client and track API) runs unmodified over real
sockets. The backend reaches it only when PROVIDER_UPSTREAM_OVERRIDE points at
a loopback address, which the backend refuses in production.

    cd backend && uv run python -m tests.fakes.providers --port 8300 \\
        --spotify-client-id fake-client-id \\
        --spotify-redirect http://127.0.0.1:3200/api/v1/providers/spotify/callback

What it checks like the real services (and records in /_control/log):
* Spotify: exact client id and redirect URI, S256 PKCE verifier against the
  challenge, single-use codes, Bearer tokens, refresh-token grants.
* Yandex ID: the library's Music app client id/secret, device codes approved
  through the control API (standing in for her tapping "Allow" on ya.ru),
  device-bound tokens that /revoke_token really invalidates.
* Ynison: `OAuth <token>` on both WebSockets, a redirect ticket, and that the
  only message ever sent is the read-only, non-player handshake.

Control API (tests drive scenarios with it; nothing secret is ever echoed):
    PUT  /_control/spotify   {"scenario": "...", "retry_after": 2}
    PUT  /_control/yandex    {"scenario": "..."}
    POST /_control/yandex/approve | /_control/yandex/deny
    POST /_control/expire-access      (every issued access token stops working)
    GET  /_control/log | /_control/state      POST /_control/reset
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from html import escape
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.websockets import WebSocketDisconnect

SPOTIFY_SCENARIOS = (
    "playing",
    "paused",
    "idle",
    "private",
    "episode",
    "local",
    "no_artwork",
    "unknown_position",
    "rate_limited",
    "quota",
    "forbidden",
    "server_error",
    "timeout",
    "bad_json",
    "revoked",
)
YANDEX_SCENARIOS = (
    "playing",
    "paused",
    "no_device",
    "offline_device",
    "no_track",
    "track_lookup_fails",
    "unauthorized",
    "go_away",
    "server_error",
    "malformed",
    "timeout",
)

SPOTIFY_TRACK = {
    "id": "4fakeTrackId0000000000",
    "name": "Fake Spotify Song",
    "type": "track",
    "is_local": False,
    "duration_ms": 200_000,
    "artists": [{"name": "Test Artist"}, {"name": "Second Artist"}],
    "album": {
        "name": "Fixture Album",
        "images": [
            {"url": "https://i.scdn.co/image/fake-cover-640", "width": 640, "height": 640},
            {"url": "https://i.scdn.co/image/fake-cover-300", "width": 300, "height": 300},
            {"url": "https://i.scdn.co/image/fake-cover-64", "width": 64, "height": 64},
        ],
    },
    "external_urls": {"spotify": "https://open.spotify.com/track/4fakeTrackId0000000000"},
}
YANDEX_TRACK_ID = "10994777"
YANDEX_ALBUM_ID = "1193829"
YANDEX_COVER = "avatars.yandex.net/get-music-content/fake/cover/%%"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class _SpotifyCode:
    challenge: str
    redirect_uri: str
    issued: float
    used: bool = False


@dataclass
class _DeviceCode:
    user_code: str
    device_id: str
    issued: float
    status: str = "pending"  # pending | approved | denied | consumed


@dataclass
class FakeState:
    spotify_client_id: str
    spotify_redirect: str
    spotify_scenario: str = "playing"
    spotify_retry_after: int = 2
    yandex_scenario: str = "playing"
    device_interval: int = 2
    # How long the "timeout" scenarios stall: longer than PROVIDER_TIMEOUT_SECONDS.
    stall_seconds: float = 6.0
    codes: dict[str, _SpotifyCode] = field(default_factory=dict)
    spotify_access: dict[str, bool] = field(default_factory=dict)  # token -> valid
    spotify_refresh: dict[str, bool] = field(default_factory=dict)
    device_codes: dict[str, _DeviceCode] = field(default_factory=dict)
    yandex_tokens: dict[str, bool] = field(default_factory=dict)  # token -> valid
    log: list[dict[str, Any]] = field(default_factory=list)

    def note(self, service: str, event: str, **details: Any) -> None:
        self.log.append({"service": service, "event": event, **details})
        del self.log[:-500]


def create_app(state: FakeState) -> FastAPI:
    app = FastAPI(title="Fake providers (tests only)", docs_url=None, redoc_url=None)
    app.state.fake = state

    # ----- control API ---------------------------------------------------------------

    @app.put("/_control/spotify")
    async def set_spotify(body: dict[str, Any]) -> dict[str, Any]:
        scenario = str(body.get("scenario", ""))
        if scenario not in SPOTIFY_SCENARIOS:
            return {"error": f"unknown scenario {scenario}"}
        state.spotify_scenario = scenario
        state.spotify_retry_after = int(body.get("retry_after", state.spotify_retry_after))
        return {"scenario": scenario}

    @app.put("/_control/yandex")
    async def set_yandex(body: dict[str, Any]) -> dict[str, Any]:
        scenario = str(body.get("scenario", ""))
        if scenario not in YANDEX_SCENARIOS:
            return {"error": f"unknown scenario {scenario}"}
        state.yandex_scenario = scenario
        return {"scenario": scenario}

    @app.post("/_control/yandex/{decision}")
    async def decide(decision: str) -> dict[str, Any]:
        pending = [c for c in state.device_codes.values() if c.status == "pending"]
        if not pending or decision not in {"approve", "deny"}:
            return {"updated": 0}
        pending[-1].status = "approved" if decision == "approve" else "denied"
        state.note("yandex", f"user_{decision}d", device_id=pending[-1].device_id)
        return {"updated": 1, "user_code": pending[-1].user_code}

    @app.post("/_control/expire-access")
    async def expire_access() -> dict[str, Any]:
        for token in state.spotify_access:
            state.spotify_access[token] = False
        return {"expired": len(state.spotify_access)}

    @app.get("/_control/log")
    async def get_log() -> list[dict[str, Any]]:
        return state.log

    @app.get("/_control/state")
    async def get_state() -> dict[str, Any]:
        return {
            "spotify_scenario": state.spotify_scenario,
            "yandex_scenario": state.yandex_scenario,
            "spotify_valid_access_tokens": sum(state.spotify_access.values()),
            "yandex_valid_tokens": sum(state.yandex_tokens.values()),
            "pending_device_codes": sum(
                1 for c in state.device_codes.values() if c.status == "pending"
            ),
        }

    @app.post("/_control/reset")
    async def reset() -> dict[str, str]:
        state.spotify_scenario = "playing"
        state.yandex_scenario = "playing"
        state.log.clear()
        return {"status": "reset"}

    # ----- Spotify accounts -----------------------------------------------------------

    @app.get("/spotify/accounts/authorize")
    async def spotify_authorize(request: Request) -> Response:
        q = request.query_params
        problems = []
        if q.get("client_id") != state.spotify_client_id:
            problems.append("INVALID_CLIENT: Invalid client")
        if q.get("redirect_uri") != state.spotify_redirect:
            problems.append("INVALID_CLIENT: Invalid redirect URI")
        if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256":
            problems.append("unsupported_response_type or PKCE method")
        if not q.get("code_challenge") or not q.get("state"):
            problems.append("missing PKCE challenge or state")
        if problems:
            state.note("spotify", "authorize_rejected", problems=problems)
            return HTMLResponse(f"<h1>{escape('; '.join(problems))}</h1>", status_code=400)
        code = secrets.token_urlsafe(24)
        state.codes[code] = _SpotifyCode(
            challenge=q["code_challenge"], redirect_uri=q["redirect_uri"], issued=time.time()
        )
        state.note("spotify", "authorize_page", scope=q.get("scope"))
        agree = f"{q['redirect_uri']}?{urlencode({'code': code, 'state': q['state']})}"
        cancel = f"{q['redirect_uri']}?{urlencode({'error': 'access_denied', 'state': q['state']})}"
        return HTMLResponse(
            "<!doctype html><html lang=en><meta name=viewport content='width=device-width'>"
            "<title>Fake Spotify</title><body style='font-family:sans-serif;padding:24px'>"
            "<p>Local test fake of Spotify's consent page.</p>"
            f"<p>Scope requested: <code>{escape(q.get('scope', ''))}</code></p>"
            f"<p><a id=agree href='{escape(agree)}'>Agree</a></p>"
            f"<p><a id=cancel href='{escape(cancel)}'>Cancel</a></p></body></html>"
        )

    @app.post("/spotify/accounts/api/token")
    async def spotify_token(request: Request) -> Response:
        if request.headers.get("content-type", "").split(";")[0] != (
            "application/x-www-form-urlencoded"
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        form = await _form(request)
        if "client_secret" in form:
            state.note("spotify", "client_secret_sent")  # PKCE apps must not send it
        if form.get("client_id") != state.spotify_client_id:
            return JSONResponse({"error": "invalid_client"}, status_code=400)
        grant = form.get("grant_type")
        if grant == "authorization_code":
            code = state.codes.get(str(form.get("code", "")))
            if code is None or code.used or time.time() - code.issued > 600:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            code.used = True
            if form.get("redirect_uri") != code.redirect_uri:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if _s256(str(form.get("code_verifier", ""))) != code.challenge:
                state.note("spotify", "pkce_failed")
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            state.note("spotify", "pkce_verified")
            return JSONResponse(_issue_spotify(state, with_refresh=True))
        if grant == "refresh_token":
            refresh = str(form.get("refresh_token", ""))
            if state.spotify_scenario == "revoked" or not state.spotify_refresh.get(refresh):
                state.note("spotify", "refresh_rejected")
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            state.note("spotify", "refreshed")
            return JSONResponse(_issue_spotify(state, with_refresh=False))
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    # ----- Spotify Web API ---------------------------------------------------------------

    @app.get("/spotify/api/v1/me/player/currently-playing")
    async def currently_playing(request: Request) -> Response:
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ")
        if not auth.startswith("Bearer ") or not state.spotify_access.get(token):
            state.note("spotify", "api_401")
            return JSONResponse(
                {"error": {"status": 401, "message": "The access token expired"}}, status_code=401
            )
        if request.query_params:
            state.note("spotify", "unexpected_query", keys=sorted(request.query_params))
        scenario = state.spotify_scenario
        state.note("spotify", "currently_playing", scenario=scenario)
        return await _spotify_response(state, scenario)

    # ----- Yandex ID OAuth -------------------------------------------------------------

    @app.post("/yandex/oauth/device/code")
    async def device_code(request: Request) -> Response:
        from app.providers.yandex import music_app_credentials

        form = await _form(request)
        client_id, _ = music_app_credentials()
        device_id = str(form.get("device_id", ""))
        if form.get("client_id") != client_id or not 6 <= len(device_id) <= 50:
            return JSONResponse({"error": "invalid_client"}, status_code=400)
        code = secrets.token_urlsafe(24)
        user_code = f"{secrets.randbelow(10**7):07d}"
        state.device_codes[code] = _DeviceCode(user_code, device_id, time.time())
        state.note("yandex", "device_code", device_name=str(form.get("device_name", "")))
        return JSONResponse(
            {
                "device_code": code,
                "user_code": user_code,
                "verification_url": "https://ya.ru/device",
                "interval": state.device_interval,
                "expires_in": 300,
            }
        )

    @app.post("/yandex/oauth/token")
    async def device_token(request: Request) -> Response:
        from app.providers.yandex import music_app_credentials

        form = await _form(request)
        client_id, client_secret = music_app_credentials()
        if form.get("client_id") != client_id or form.get("client_secret") != client_secret:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if form.get("grant_type") != "device_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        entry = state.device_codes.get(str(form.get("code", "")))
        if entry is None or entry.status == "consumed":
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if time.time() - entry.issued > 300:
            return JSONResponse({"error": "expired_token"}, status_code=400)
        if entry.status == "pending":
            return JSONResponse({"error": "authorization_pending"}, status_code=400)
        if entry.status == "denied":
            return JSONResponse({"error": "access_denied"}, status_code=400)
        entry.status = "consumed"
        token = "y0_fake_" + secrets.token_urlsafe(32)
        state.yandex_tokens[token] = True
        state.note("yandex", "token_issued", device_id=entry.device_id)
        return JSONResponse(
            {
                "token_type": "bearer",
                "access_token": token,
                "expires_in": 31_536_000,
                "refresh_token": "1:fake:" + secrets.token_urlsafe(16),
            }
        )

    @app.post("/yandex/oauth/revoke_token")
    async def revoke_token(request: Request) -> Response:
        from app.providers.yandex import music_app_credentials

        form = await _form(request)
        client_id, client_secret = music_app_credentials()
        if form.get("client_id") != client_id or form.get("client_secret") != client_secret:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        token = str(form.get("access_token", ""))
        if not state.yandex_tokens.get(token):
            state.note("yandex", "revoke_unknown_token")
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        state.yandex_tokens[token] = False
        state.note("yandex", "token_revoked")
        return JSONResponse({"status": "ok"})

    # ----- Yandex Music API (track metadata) -------------------------------------------------

    @app.post("/yandex/api/tracks")
    async def yandex_tracks(request: Request) -> Response:
        if not _yandex_token_ok(state, request.headers.get("authorization", "")):
            return JSONResponse(
                {"error": {"name": "session-expired", "message": "Unauthorized"}}, status_code=401
            )
        if state.yandex_scenario == "track_lookup_fails":
            return JSONResponse({"error": "internal"}, status_code=500)
        form = await _form(request)
        state.note("yandex", "tracks", ids=str(form.get("track-ids", "")))
        return JSONResponse(
            {
                "invocationInfo": {"req-id": "fake", "hostname": "fake"},
                "result": [
                    {
                        "id": YANDEX_TRACK_ID,
                        "realId": YANDEX_TRACK_ID,
                        "title": "Fake Yandex Song",
                        "available": True,
                        "durationMs": 215_000,
                        "coverUri": YANDEX_COVER,
                        "artists": [{"id": 1, "name": "Fixture Singer", "various": False}],
                        "albums": [
                            {
                                "id": int(YANDEX_ALBUM_ID),
                                "title": "Fake Album",
                                "coverUri": YANDEX_COVER,
                            }
                        ],
                    }
                ],
            }
        )

    # ----- Ynison (two WebSockets: redirector, then state) -------------------------------------

    @app.websocket("/yandex/ynison/redirector.YnisonRedirectService/GetRedirectToYnison")
    async def ynison_redirect(websocket: WebSocket) -> None:
        if not _yandex_token_ok(state, websocket.headers.get("authorization", "")):
            state.note("ynison", "redirect_unauthorized")
            await websocket.close(code=4401)  # before accept: the client sees HTTP 403
            return
        if state.yandex_scenario == "unauthorized":
            await websocket.close(code=4401)
            return
        await websocket.accept()
        await websocket.send_text(json.dumps(_redirect(websocket.headers.get("host", "127.0.0.1"))))
        await _drain(websocket)

    @app.websocket("/yandex/ynison-state/ynison_state.YnisonStateService/PutYnisonState")
    async def ynison_state_socket(websocket: WebSocket) -> None:
        if not _yandex_token_ok(state, websocket.headers.get("authorization", "")):
            state.note("ynison", "state_unauthorized")
            await websocket.close(code=4401)
            return
        await websocket.accept()
        try:
            first = json.loads(await websocket.receive_text())
        except (WebSocketDisconnect, ValueError):
            return
        full = first.get("update_full_state") or first.get("updateFullState") or {}
        capabilities = (full.get("device") or {}).get("capabilities") or {}
        read_only = not capabilities.get("can_be_player", capabilities.get("canBePlayer", False))
        state.note("ynison", "handshake", read_only=read_only, keys=sorted(first))
        scenario = state.yandex_scenario
        if scenario == "timeout":
            await _drain(websocket)
            return
        if scenario == "malformed":
            await websocket.send_text("<html>Service changed</html>")
        elif scenario == "go_away":
            await websocket.send_text(
                json.dumps(
                    {
                        "error": {
                            "message": "go away",
                            "http_code": 429,
                            "details": {"ynison-go-away-for-seconds": "3"},
                        }
                    }
                )
            )
        elif scenario == "server_error":
            await websocket.send_text(
                json.dumps(
                    {
                        "error": {
                            "message": "unavailable",
                            "grpc_code": 14,
                            "details": {"ynison-backoff-millis": "1000:2000"},
                        }
                    }
                )
            )
        else:
            await websocket.send_text(json.dumps(_ynison_state(scenario)))
        # Anything else the client sends is recorded: it must never send commands.
        try:
            while True:
                extra = await websocket.receive_text()
                state.note("ynison", "unexpected_message", size=len(extra))
        except WebSocketDisconnect:
            return

    return app


# ----- helpers ------------------------------------------------------------------------------


async def _form(request: Request) -> dict[str, str]:
    """application/x-www-form-urlencoded body (without needing python-multipart)."""
    return dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))


def _issue_spotify(state: FakeState, *, with_refresh: bool) -> dict[str, Any]:
    access = "BQ-fake-" + secrets.token_urlsafe(24)
    state.spotify_access[access] = True
    body: dict[str, Any] = {
        "access_token": access,
        "token_type": "Bearer",
        "scope": "user-read-currently-playing",
        "expires_in": 3600,
    }
    if with_refresh:
        refresh = "AQ-fake-" + secrets.token_urlsafe(24)
        state.spotify_refresh[refresh] = True
        body["refresh_token"] = refresh
    return body


async def _spotify_response(state: FakeState, scenario: str) -> Response:
    base: dict[str, Any] = {
        "timestamp": _now_ms(),
        "progress_ms": 42_000,
        "is_playing": True,
        "currently_playing_type": "track",
        "item": SPOTIFY_TRACK,
        "device": {"is_private_session": False},
    }
    match scenario:
        case "paused":
            base["is_playing"] = False
        case "idle":
            return Response(status_code=204)
        case "private":
            base["device"] = {"is_private_session": True}
        case "episode":
            base["item"] = None
            base["currently_playing_type"] = "episode"
        case "local":
            base["item"] = {
                **SPOTIFY_TRACK,
                "is_local": True,
                "id": None,
                "name": "My Own Recording",
                "album": {"name": "", "images": []},
                "external_urls": {},
            }
        case "no_artwork":
            base["item"] = {**SPOTIFY_TRACK, "album": {"name": "No Cover Album", "images": []}}
        case "unknown_position":
            base.pop("progress_ms")
        case "rate_limited":
            return Response(
                status_code=429, headers={"Retry-After": str(state.spotify_retry_after)}
            )
        case "quota":
            return JSONResponse(
                {"error": {"status": 429, "message": "quota", "reason": "QUOTA_EXCEEDED"}},
                status_code=429,
                headers={"Retry-After": str(state.spotify_retry_after)},
            )
        case "forbidden":
            return JSONResponse({"error": {"status": 403, "message": "Forbidden"}}, status_code=403)
        case "server_error":
            return Response(status_code=503)
        case "timeout":
            await asyncio.sleep(state.stall_seconds)
        case "bad_json":
            return Response("{not json", media_type="application/json")
        case "revoked":
            return JSONResponse({"error": {"status": 401, "message": "revoked"}}, status_code=401)
    return JSONResponse(base)


def _redirect(host: str) -> dict[str, Any]:
    from yandex_music.ynison.models.ynison_redirect import KeepAliveParams, RedirectResponse

    redirect = RedirectResponse(
        host=f"{host}/yandex/ynison-state",
        redirect_ticket="ticket-" + secrets.token_hex(8),
        session_id=secrets.randbelow(10**12) + 1,
        keep_alive_params=KeepAliveParams(
            keep_alive_time_seconds=20, keep_alive_timeout_seconds=20
        ),
    )
    return dict(redirect.to_dict())


def _yandex_token_ok(state: FakeState, header: str) -> bool:
    return header.startswith("OAuth ") and bool(state.yandex_tokens.get(header[6:]))


def _ynison_state(scenario: str) -> dict[str, Any]:
    from yandex_music.ynison.models import ynison_state as ys

    now = _now_ms()
    playable = ys.Playable(
        playable_id=YANDEX_TRACK_ID,
        album_id_optional=YANDEX_ALBUM_ID,
        playable_type=ys.PlayablePlayableType.TRACK,
        title="Fake Ynison Title",
        cover_url_optional=YANDEX_COVER,
    )
    status = ys.PlayingStatus(
        progress_ms=61_000,
        duration_ms=215_000,
        paused=scenario == "paused",
        playback_speed=1.0,
        version=ys.UpdateVersion(device_id="her-phone", version=7, timestamp_ms=now),
    )
    queue = ys.PlayerQueue(
        current_playable_index=-1 if scenario == "no_track" else 0,
        playable_list=[] if scenario == "no_track" else [playable],
    )
    device = ys.Device(
        info=ys.DeviceInfo(device_id="her-phone", title="iPhone"),
        is_offline=scenario == "offline_device",
    )
    response = ys.PutYnisonStateResponse(
        player_state=ys.PlayerState(status=status, player_queue=queue),
        devices=[device],
        active_device_id_optional="" if scenario == "no_device" else "her-phone",
        timestamp_ms=now,
    )
    return dict(response.to_dict())


async def _drain(websocket: WebSocket) -> None:
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Fake Spotify/Yandex for local tests.")
    parser.add_argument("--port", type=int, default=8300)
    parser.add_argument("--spotify-client-id", required=True)
    parser.add_argument("--spotify-redirect", required=True)
    parser.add_argument("--device-interval", type=int, default=2)
    args = parser.parse_args(argv)
    state = FakeState(
        spotify_client_id=args.spotify_client_id,
        spotify_redirect=args.spotify_redirect,
        device_interval=args.device_interval,
    )
    # Loopback only: this is a test tool with an unauthenticated control API.
    uvicorn.run(create_app(state), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
