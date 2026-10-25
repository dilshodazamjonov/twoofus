from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.db.types import UTCDateTime
from app.models.enums import AuthFlowKind, AuthFlowStatus, ConnectionStatus, ProviderName, sql_in


class ProviderConnection(Base):
    """A user's link to their own music service (at most one per user).

    Tokens are stored only as AES-GCM ciphertext (see app.core.crypto). The
    remaining columns are health/freshness metadata; no playback content or
    listening history is ever written to the database.
    """

    __tablename__ = "provider_connections"
    __table_args__ = (
        CheckConstraint(f"provider IN ({sql_in(ProviderName)})", name="provider_valid"),
        CheckConstraint(f"status IN ({sql_in(ConnectionStatus)})", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default=ConnectionStatus.ACTIVE.value)

    access_token_enc: Mapped[str | None] = mapped_column(Text, default=None)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, default=None)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    scopes: Mapped[str | None] = mapped_column(String(255), default=None)
    # Incremented on every credential change; used for optimistic concurrency
    # when two requests race to refresh the same token.
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    # When the user (re)authorised; Spotify refresh tokens expire 6 months later.
    authorized_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    last_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_error_code: Mapped[str | None] = mapped_column(String(48), default=None)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    backoff_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    reauth_required_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ProviderAuthFlow(Base):
    """A short-lived, pending provider authorisation bound to one app session.

    * Spotify (Authorization Code + PKCE): ``state_hash`` + encrypted code verifier.
    * Yandex (OAuth device flow): encrypted device code + the user code to show.
    """

    __tablename__ = "provider_auth_flows"
    __table_args__ = (
        CheckConstraint(f"provider IN ({sql_in(ProviderName)})", name="provider_valid"),
        CheckConstraint(f"kind IN ({sql_in(AuthFlowKind)})", name="kind_valid"),
        CheckConstraint(f"status IN ({sql_in(AuthFlowStatus)})", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("auth_sessions.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=AuthFlowStatus.PENDING.value)
    state_hash: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    secret_enc: Mapped[str | None] = mapped_column(Text, default=None)
    user_code: Mapped[str | None] = mapped_column(String(32), default=None)
    verification_url: Mapped[str | None] = mapped_column(String(255), default=None)
    poll_interval_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    next_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    error_code: Mapped[str | None] = mapped_column(String(48), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
