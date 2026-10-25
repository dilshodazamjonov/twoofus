"""Small in-memory sliding-window rate limiter.

Good enough for a two-person app running as a single process. A deployment
with several backend processes needs a shared store (see docs/SECURITY.md).
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


class RateLimiter:
    def __init__(self, monotonic: Callable[[], float] = time.monotonic, max_keys: int = 10_000):
        self._now = monotonic
        self._hits: dict[str, deque[float]] = {}
        self._max_keys = max_keys

    def _prune(self, now: float) -> None:
        if len(self._hits) < self._max_keys:
            return
        horizon = now - 24 * 3600
        for key in [k for k, q in self._hits.items() if not q or q[-1] < horizon]:
            del self._hits[key]

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
BOOTSTRAP_PER_IP = Limit(attempts=5, window_seconds=15 * 60)
SENSITIVE_PER_USER = Limit(attempts=10, window_seconds=15 * 60)
