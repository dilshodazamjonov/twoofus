"""Pure-ASGI middleware: proxy authentication, request body limit, request log.

They are plain ASGI callables (not Starlette's BaseHTTPMiddleware) so they can
refuse a request before any of its body is read, and see responses produced by
Starlette's own error handling.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

logger = logging.getLogger("app.request")

PROXY_AUTH_HEADER = "x-twoofus-proxy-auth"
REQUEST_ID_HEADER = "x-request-id"
# The largest legitimate body (accepting an invitation) is well under 1 KiB.
MAX_BODY_BYTES = 64 * 1024
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cross-origin-resource-policy", b"same-origin"),
)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if key == name:
            return bytes(value).decode("latin-1")
    return None


async def send_json_error(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *SECURITY_HEADERS,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ProxyAuthMiddleware:
    """Refuse requests that did not come through the same-origin proxy.

    The reverse proxy (Caddy, or the Next.js server) adds the shared secret to
    every request it forwards. Liveness (``/api/v1/health``) stays open so the
    container health check works from inside the container.
    """

    def __init__(self, app: ASGIApp, *, secret: str, open_paths: frozenset[str]) -> None:
        self.app = app
        self._secret = secret.encode()
        self._open_paths = open_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self._open_paths:
            await self.app(scope, receive, send)
            return
        presented = (_header(scope, PROXY_AUTH_HEADER.encode()) or "").encode("latin-1")
        if not hmac.compare_digest(presented, self._secret):
            await send_json_error(
                send, 403, "proxy_required", "This API is only reachable through the app."
            )
            return
        await self.app(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


class _Disconnected(Exception):
    pass


class BodyLimitMiddleware:
    """Reject request bodies over ``max_bytes`` with 413, without buffering more.

    A declared Content-Length is checked up front. Bodies without one (chunked)
    are read here up to the limit and then replayed to the application.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared is not None:
            if not declared.isdigit():
                await send_json_error(send, 400, "bad_request", "Invalid Content-Length.")
                return
            if int(declared) > self.max_bytes:
                await self._too_large(send)
                return
        try:
            chunks = await self._read_body(receive)
        except _BodyTooLarge:
            await self._too_large(send)
            return
        except _Disconnected:
            return  # the client went away before sending the whole body

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()  # e.g. http.disconnect

        await self.app(scope, replay, send)

    async def _read_body(self, receive: Receive) -> list[bytes]:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                raise _Disconnected
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                raise _BodyTooLarge
            chunks.append(chunk)
            if not message.get("more_body", False):
                return chunks

    async def _too_large(self, send: Send) -> None:
        await send_json_error(send, 413, "payload_too_large", "The request body is too large.")


class RequestLogMiddleware:
    """One log line per request: method, path (never the query), status, time.

    Query strings are left out on purpose: OAuth callbacks carry ``code`` and
    ``state``. A request id (the proxy's ``X-Request-ID`` when it is a plain
    short token, else a new one) is returned to the client and logged, so a
    user-visible problem can be matched to a log line without logging content.
    Every API response also gets the API's security headers.
    """

    def __init__(self, app: ASGIApp, *, skip_security_headers: tuple[str, ...] = ()) -> None:
        self.app = app
        self._skip = skip_security_headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        incoming = _header(scope, REQUEST_ID_HEADER.encode()) or ""
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:16]
        path = str(scope.get("path", ""))
        add_security = not path.startswith(self._skip)
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers", []))
                present = {bytes(k).lower() for k, _ in headers}
                if add_security:
                    headers.extend(h for h in SECURITY_HEADERS if h[0] not in present)
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "%s %s -> %d (%.0f ms)",
                scope.get("method", "?"),
                path,
                status,
                elapsed_ms,
                extra={
                    "http_method": scope.get("method", "?"),
                    "http_path": path,
                    "http_status": status,
                    "duration_ms": round(elapsed_ms, 1),
                    "request_id": request_id,
                },
            )
