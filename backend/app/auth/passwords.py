"""Argon2id password hashing (argon2-cffi, RFC 9106 low-memory defaults).

Hashing is CPU-heavy, so it runs in a worker thread to keep the event loop
responsive. Unknown usernames are verified against a dummy hash so response
timing does not reveal whether an account exists.
"""

from __future__ import annotations

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256


class Passwords:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()
        self._dummy_hash = self._hasher.hash("timing-equaliser, not a real password")

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, stored_hash: str | None, password: str) -> bool:
        return await asyncio.to_thread(self._verify_sync, stored_hash, password)

    def _verify_sync(self, stored_hash: str | None, password: str) -> bool:
        try:
            self._hasher.verify(stored_hash or self._dummy_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        return stored_hash is not None

    def needs_rehash(self, stored_hash: str) -> bool:
        return self._hasher.check_needs_rehash(stored_hash)


def password_problem(password: str, *, username: str) -> str | None:
    """Return a human-readable problem with ``password``, or ``None`` if acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use at most {MAX_PASSWORD_LENGTH} characters."
    if password.strip().lower() == username.strip().lower():
        return "The password must differ from the username."
    if len(set(password)) < 4:
        return "That password is too repetitive."
    return None
