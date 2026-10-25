from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import OutModel

ProviderLiteral = Literal["spotify", "yandex", "demo"]


class ProviderAvailabilityOut(OutModel):
    name: ProviderLiteral
    label: str
    available: bool = Field(description="Enabled and configured on this server.")
    experimental: bool
    official_api: bool


class ConnectionOut(OutModel):
    provider: ProviderLiteral
    status: Literal["active", "reauth_required"]
    authorized_at: datetime
    reauthorize_by: datetime | None = Field(
        description="Spotify refresh tokens stop working 6 months after authorisation."
    )
    last_fetch_at: datetime | None
    last_success_at: datetime | None
    last_error_code: str | None
    last_error_at: datetime | None
    backoff_until: datetime | None


class DeviceFlowOut(OutModel):
    status: Literal["pending", "completed", "failed", "expired", "cancelled"]
    user_code: str | None
    verification_url: str | None
    expires_at: datetime
    poll_interval_seconds: int
    error_code: str | None


class PendingAuthorizationOut(OutModel):
    provider: ProviderLiteral
    kind: Literal["oauth_pkce", "device_code"]
    expires_at: datetime


class ProvidersOut(OutModel):
    providers: list[ProviderAvailabilityOut]
    connection: ConnectionOut | None
    pending_authorization: PendingAuthorizationOut | None


class AuthorizeOut(OutModel):
    authorization_url: str


class ConfigProviderOut(OutModel):
    available: bool
    experimental: bool


class ConfigOut(OutModel):
    app_name: str
    environment: str
    demo_mode: bool
    providers: dict[str, ConfigProviderOut]
    now_playing_ttl_seconds: int
    sharing_notice_version: str
    api_version: str


class HealthOut(OutModel):
    status: Literal["ok"]


class ReadyOut(OutModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "error"]
    migrations: Literal["ok", "pending", "unknown"]
