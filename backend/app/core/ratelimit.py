"""Small in-memory sliding-window rate limiter.

Good enough for a two-person app running as a single process. A deployment
with several backend processes needs a shared store.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.core.errors import RateLimited


@dataclass(frozen=True, slots=True)
class Limit:
    attempts: int
    window_seconds: int


# Keys (they include client IPs) are forgotten this long after their last hit:
# longer than the longest window, short enough not to keep IPs around.
_FORGET_AFTER_SECONDS = 24 * 3600
_PRUNE_EVERY_SECONDS = 600


class RateLimiter:
    def __init__(self, monotonic: Callable[[], float] = time.monotonic, max_keys: int = 10_000):
        self._now = monotonic
        self._hits: dict[str, deque[float]] = {}
        self._max_keys = max_keys
        self._last_prune = monotonic()

    def _prune(self, now: float) -> None:
        if len(self._hits) < self._max_keys and now - self._last_prune < _PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        horizon = now - _FORGET_AFTER_SECONDS
        for key in [k for k, q in self._hits.items() if not q or q[-1] < horizon]:
            del self._hits[key]

    def tracked_keys(self) -> int:
        return len(self._hits)

    def check(self, key: str, limit: Limit) -> None:
        """Record one attempt for ``key``; raise :class:`RateLimited` if over the limit."""
        now = self._now()
        self._prune(now)
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - limit.window_seconds:
            hits.popleft()
        if len(hits) >= limit.attempts:
            retry_after = math.ceil(hits[0] + limit.window_seconds - now)
            raise RateLimited(retry_after)
        hits.append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


LOGIN_PER_IP = Limit(attempts=20, window_seconds=15 * 60)
LOGIN_PER_USERNAME = Limit(attempts=10, window_seconds=15 * 60)
INVITE_PER_IP = Limit(attempts=15, window_seconds=15 * 60)
SENSITIVE_PER_USER = Limit(attempts=10, window_seconds=15 * 60)
# Starting a provider authorisation (each one may call the provider).
CONNECT_PER_USER = Limit(attempts=20, window_seconds=15 * 60)
# The Yandex device-flow poll endpoint (the UI polls every ~5 s for <= 15 min).
DEVICE_POLL_PER_USER = Limit(attempts=300, window_seconds=15 * 60)
# Settings writes: sharing switch (it also drops the now-playing cache), name.
SETTINGS_PER_USER = Limit(attempts=60, window_seconds=15 * 60)
INVITE_CREATE_PER_USER = Limit(attempts=30, window_seconds=15 * 60)
# Tulips: a few in a row are fine; a flood is not.
TULIP_PER_MINUTE = Limit(attempts=10, window_seconds=60)
TULIP_PER_DAY = Limit(attempts=200, window_seconds=24 * 3600)
