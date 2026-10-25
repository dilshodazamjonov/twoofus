from __future__ import annotations

from enum import StrEnum


class MemberRole(StrEnum):
    OWNER = "owner"
    PARTNER = "partner"


class ProviderName(StrEnum):
    SPOTIFY = "spotify"
    YANDEX = "yandex"
    DEMO = "demo"


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    REAUTH_REQUIRED = "reauth_required"


class AuthFlowKind(StrEnum):
    OAUTH_PKCE = "oauth_pkce"
    DEVICE_CODE = "device_code"


class AuthFlowStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def sql_in(values: type[StrEnum]) -> str:
    """Render ``'a', 'b'`` for CHECK constraints."""
    return ", ".join(f"'{v.value}'" for v in values)
