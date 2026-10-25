"""Opaque tokens, hashing of high-entropy secrets, and signed CSRF tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token(nbytes: int = 32) -> str:
    """Random URL-safe token (256 bits by default)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 of a high-entropy random token.

    Fine for session/invitation/state secrets because they are 256-bit random
    values (not guessable passwords), so a fast hash does not weaken them; the
    database only ever stores this digest.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class CsrfSigner:
    """Signed double-submit CSRF tokens (OWASP "signed double-submit cookie").

    Token format ``<nonce>.<hmac>``; the HMAC binds the nonce to the current
    session id (or to ``anon`` before login), so a token planted by another
    origin or carried over from a different session is rejected.
    """

    def __init__(self, secret_key: str) -> None:
        self._key = hmac.new(secret_key.encode(), b"twoofus-csrf-v1", hashlib.sha256).digest()

    def _sign(self, nonce: str, binding: str) -> str:
        return hmac.new(self._key, f"{binding}:{nonce}".encode(), hashlib.sha256).hexdigest()

    def issue(self, binding: str) -> str:
        nonce = secrets.token_urlsafe(18)
        return f"{nonce}.{self._sign(nonce, binding)}"

    def verify(self, token: str, binding: str) -> bool:
        nonce, sep, signature = token.partition(".")
        if not sep or not nonce or not signature:
            return False
        return hmac.compare_digest(signature, self._sign(nonce, binding))
