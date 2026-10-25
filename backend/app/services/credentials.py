"""Encryption contexts (AEAD associated data) for stored secrets.

A ciphertext only decrypts under the exact context it was written with, so a
token copied to another user's row, provider or field is rejected.
"""

from __future__ import annotations

import uuid


def token_context(user_id: uuid.UUID, provider: str, field: str) -> str:
    return f"provider_connection:{user_id}:{provider}:{field}"


def flow_context(flow_id: uuid.UUID, field: str) -> str:
    return f"provider_auth_flow:{flow_id}:{field}"
