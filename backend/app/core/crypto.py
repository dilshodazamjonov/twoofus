"""Encryption at rest for provider credentials (AES-256-GCM).

Ciphertext format: ``v1.<key id>.<base64url(nonce || ciphertext+tag)>``.

* The key id lets several keys coexist, so keys can be rotated: put the new key
  first in ``TOKEN_ENCRYPTION_KEYS``; old keys stay readable until re-encrypted.
* Every value is bound to a *context* string (e.g. which user/provider/field it
  belongs to) through GCM associated data, so a ciphertext copied into another
  row or column fails to decrypt instead of being silently accepted.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = "v1"
_NONCE_BYTES = 12


class DecryptionError(Exception):
    """Raised when a stored secret cannot be decrypted (wrong key/context or tampering)."""


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"twoofus-key-id:" + key).hexdigest()[:8]


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class TokenCipher:
    def __init__(self, keys: list[bytes]) -> None:
        if not keys:
            raise ValueError("at least one encryption key is required")
        for key in keys:
            if len(key) != 32:
                raise ValueError("encryption keys must be 32 bytes (AES-256)")
        self._primary_id = _key_id(keys[0])
        self._keys = {_key_id(k): AESGCM(k) for k in keys}

    @staticmethod
    def _aad(context: str) -> bytes:
        return f"twoofus/{_VERSION}/{context}".encode()

    def encrypt(self, plaintext: str, *, context: str) -> str:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._keys[self._primary_id].encrypt(nonce, plaintext.encode(), self._aad(context))
        return f"{_VERSION}.{self._primary_id}.{_b64e(nonce + sealed)}"

    def decrypt(self, token: str, *, context: str) -> str:
        try:
            version, key_id, payload = token.split(".", 2)
        except ValueError as exc:
            raise DecryptionError("malformed ciphertext") from exc
        if version != _VERSION or key_id not in self._keys:
            raise DecryptionError("unknown ciphertext version or key")
        try:
            raw = _b64d(payload)
            plaintext = self._keys[key_id].decrypt(
                raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], self._aad(context)
            )
        except (InvalidTag, ValueError) as exc:
            raise DecryptionError("ciphertext failed authentication") from exc
        return plaintext.decode()

    def needs_reencryption(self, token: str) -> bool:
        parts = token.split(".", 2)
        return len(parts) != 3 or parts[1] != self._primary_id


def generate_key() -> str:
    """Return a new random key in the format TOKEN_ENCRYPTION_KEYS expects."""
    return _b64e(os.urandom(32))
