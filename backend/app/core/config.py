"""Application settings, loaded from the environment and ``backend/.env``.

Secrets have no defaults on purpose: the app refuses to start without a real
``SECRET_KEY`` and ``TOKEN_ENCRYPTION_KEYS`` instead of silently using an
insecure placeholder.
"""

from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = BACKEND_DIR / "data" / "twoofus.db"
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{DEFAULT_SQLITE_PATH}"

# The only callback path the backend serves; the redirect URI must point at it.
SPOTIFY_CALLBACK_PATH = "/api/v1/providers/spotify/callback"
# The scopes for GET /v1/me/player/currently-playing and
# /v1/me/player/recently-played (verified in the official OpenAPI spec).
# Not configurable on purpose: least privilege.
SPOTIFY_SCOPES = ("user-read-currently-playing", "user-read-recently-played")

# Bump when the text users acknowledge before turning sharing on changes.
SHARING_NOTICE_VERSION = "2026-10-25.3"

_PLACEHOLDER_MARKERS = ("change_me", "changeme", "replace_me", "<", "example")

Environment = Literal["development", "test", "production"]


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _decode_key(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    try:
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("TOKEN_ENCRYPTION_KEYS entries must be url-safe base64") from exc
    if len(key) != 32:
        raise ValueError("each TOKEN_ENCRYPTION_KEYS entry must decode to exactly 32 bytes")
    return key


def _env_file() -> Path | None:
    # TWOOFUS_ENV_FILE lets scripts point at another file ("" = none), e.g. the
    # smoke test, which must not pick up the developer's backend/.env.
    override = os.environ.get("TWOOFUS_ENV_FILE")
    if override is None:
        return BACKEND_DIR / ".env"
    return Path(override) if override else None


def _secrets_dir() -> Path | None:
    # Deployments mount secrets as files (Docker secrets, systemd credentials):
    # TWOOFUS_SECRETS_DIR=/run/secrets reads e.g. /run/secrets/secret_key. Each
    # file holds one value; environment variables still take precedence.
    override = os.environ.get("TWOOFUS_SECRETS_DIR", "")
    return Path(override) if override else None


_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=_env_file(),
    env_file_encoding="utf-8",
    secrets_dir=_secrets_dir(),
    extra="ignore",
    case_sensitive=False,
    # Never echo raw values (secrets included) in validation errors/tracebacks.
    hide_input_in_errors=True,
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def normalize_database_url(value: str) -> str:
    value = value.strip() or DEFAULT_DATABASE_URL
    # Hosting providers often hand out postgres:// URLs; use psycopg 3.
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix) :]
    if value.startswith("sqlite://") and not value.startswith("sqlite+aiosqlite://"):
        return "sqlite+aiosqlite://" + value[len("sqlite://") :]
    return value


class DatabaseSettings(BaseSettings):
    """Just the database URL; used by Alembic so migrations need no app secrets."""

    model_config = _SETTINGS_CONFIG

    database_url: str = DEFAULT_DATABASE_URL

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)


class Settings(BaseSettings):
    model_config = _SETTINGS_CONFIG

    app_name: str = Field(default="JustTheTwoOfUs", min_length=1, max_length=40)
    environment: Environment = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # "json" (one object per line, for log collectors) or "text". Default:
    # json in production, text elsewhere.
    log_format: Literal["json", "text"] | None = None

    # Browser-facing origin (the Next.js app that proxies /api to FastAPI).
    public_app_url: str = "http://127.0.0.1:3000"
    # Extra origins allowed to send state-changing requests (comma separated).
    extra_allowed_origins: str = ""
    database_url: str = DEFAULT_DATABASE_URL

    secret_key: SecretStr
    token_encryption_keys: SecretStr

    # Shared secret the same-origin reverse proxy (Caddy in deploy/, or the
    # Next.js server) adds to every request it forwards, as the
    # X-TwoOfUs-Proxy-Auth header. When set, FastAPI refuses requests without
    # it, so the API is reachable only through the proxy. Required in production.
    proxy_shared_secret: SecretStr | None = None

    cookie_secure: bool | None = None
    session_ttl_days: int = Field(default=30, ge=1, le=365)
    session_idle_days: int = Field(default=14, ge=1, le=365)
    session_rotate_hours: int = Field(default=24, ge=1, le=24 * 30)
    invite_ttl_hours: int = Field(default=48, ge=1, le=24 * 7)

    demo_mode: bool = False

    spotify_client_id: str = ""
    spotify_redirect_uri: str = ""

    yandex_enabled: bool = True
    yandex_music_web_base: str = "https://music.yandex.ru"

    # 15-60 s protects the providers' quotas; only a local test fake may go lower.
    now_playing_ttl_seconds: int = Field(default=20, ge=1, le=60)
    provider_timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)

    # TESTING ONLY. Sends every server-side Spotify/Yandex call to a local fake
    # (scripts/fake_providers.py) instead of the real hosts, so the real adapter
    # code can be exercised over HTTP. Loopback http only; refused in production.
    provider_upstream_override: str = ""

    @field_validator("public_app_url", "yandex_music_web_base")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return value

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        secret = self.secret_key.get_secret_value()
        if len(secret) < 32 or any(m in secret.lower() for m in _PLACEHOLDER_MARKERS):
            raise ValueError(
                "SECRET_KEY must be a random value of at least 32 characters "
                "(generate one with: python -m app.cli.keys)"
            )
        if any(
            m in self.token_encryption_keys.get_secret_value().lower() for m in _PLACEHOLDER_MARKERS
        ):
            raise ValueError("TOKEN_ENCRYPTION_KEYS still contains a placeholder value")
        self.encryption_keys()  # raises on malformed keys

        if self.proxy_shared_secret is not None:
            proxy_secret = self.proxy_shared_secret.get_secret_value()
            if proxy_secret == "":
                self.proxy_shared_secret = None
            elif len(proxy_secret) < 32 or any(
                m in proxy_secret.lower() for m in _PLACEHOLDER_MARKERS
            ):
                raise ValueError(
                    "PROXY_SHARED_SECRET must be empty or a random value of at least 32 characters"
                )

        if self.provider_upstream_override:
            self.provider_upstream_override = self._validated_upstream_override()
        elif self.now_playing_ttl_seconds < 15:
            raise ValueError(
                "NOW_PLAYING_TTL_SECONDS must be between 15 and 60 (lower values are only "
                "allowed against a local test fake)"
            )

        if self.cookie_secure is None:
            self.cookie_secure = self.public_app_url.startswith("https://")

        if self.spotify_client_id and not self.spotify_redirect_uri:
            raise ValueError("SPOTIFY_REDIRECT_URI is required when SPOTIFY_CLIENT_ID is set")
        if self.spotify_redirect_uri:
            self._validate_spotify_redirect_uri()

        if self.environment == "production":
            if not self.public_app_url.startswith("https://"):
                raise ValueError("PUBLIC_APP_URL must use https:// in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must not be disabled in production")
            if self.demo_mode:
                # Invented songs must never appear in a real deployment.
                raise ValueError("DEMO_MODE must be false in production")
            if self.provider_upstream_override:
                raise ValueError("PROVIDER_UPSTREAM_OVERRIDE is for local tests; leave it empty")
            if self.proxy_shared_secret is None:
                raise ValueError(
                    "PROXY_SHARED_SECRET is required in production: the API must only be "
                    "reachable through the same-origin proxy"
                )
            if self.log_level == "DEBUG":
                raise ValueError("LOG_LEVEL=DEBUG is not allowed in production")
        if self.log_format is None:
            self.log_format = "json" if self.environment == "production" else "text"
        return self

    def _validated_upstream_override(self) -> str:
        parts = urlsplit(self.provider_upstream_override.strip())
        try:
            port = parts.port
        except ValueError:
            port = None
        if (
            parts.scheme != "http"
            or (parts.hostname or "").lower() not in _LOOPBACK_HOSTS
            or port is None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
        ):
            raise ValueError(
                "PROVIDER_UPSTREAM_OVERRIDE must look like http://127.0.0.1:<port> "
                "(a local test fake only)"
            )
        return f"http://{parts.netloc.lower()}"

    def _validate_spotify_redirect_uri(self) -> None:
        # https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
        uri = self.spotify_redirect_uri
        parts = urlsplit(uri)
        host = (parts.hostname or "").lower()
        if host == "localhost":
            raise ValueError(
                "Spotify rejects 'localhost' redirect URIs; use http://127.0.0.1:<port>/... locally"
            )
        loopback = host in {"127.0.0.1", "::1"}
        if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
            raise ValueError("SPOTIFY_REDIRECT_URI must be https (or http on 127.0.0.1 / [::1])")
        if parts.path != SPOTIFY_CALLBACK_PATH or parts.query or parts.fragment:
            raise ValueError(f"SPOTIFY_REDIRECT_URI path must be exactly {SPOTIFY_CALLBACK_PATH}")
        if _origin(uri) != _origin(self.public_app_url):
            raise ValueError(
                "SPOTIFY_REDIRECT_URI must be on the same origin as PUBLIC_APP_URL, otherwise "
                "the browser will not send the session cookie with the OAuth callback"
            )

    # ----- derived values -------------------------------------------------

    def encryption_keys(self) -> list[bytes]:
        raw = [k.strip() for k in self.token_encryption_keys.get_secret_value().split(",")]
        keys = [_decode_key(k) for k in raw if k]
        if not keys:
            raise ValueError("TOKEN_ENCRYPTION_KEYS must contain at least one key")
        return keys

    @property
    def public_origin(self) -> str:
        return _origin(self.public_app_url)

    @property
    def allowed_origins(self) -> frozenset[str]:
        extra = {_origin(o.strip()) for o in self.extra_allowed_origins.split(",") if o.strip()}
        return frozenset({self.public_origin, *extra})

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def demo_controls_enabled(self) -> bool:
        """Scenario switching for the Demo provider: development/test only."""
        return self.demo_mode and self.environment != "production"

    @property
    def spotify_configured(self) -> bool:
        return bool(self.spotify_client_id and self.spotify_redirect_uri)

    @property
    def secure_cookies(self) -> bool:
        return bool(self.cookie_secure)

    @property
    def upstream_override(self) -> str | None:
        return self.provider_upstream_override or None


class ConfigError(RuntimeError):
    """Invalid configuration, described without echoing any configured values."""


def describe_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid configuration (backend/.env or environment variables):"]
    for error in exc.errors(include_url=False, include_input=False):
        name = "_".join(str(part) for part in error["loc"]).upper()
        message = str(error["msg"]).removeprefix("Value error, ")
        lines.append(f"  - {name}: {message}" if name else f"  - {message}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings from the environment / backend/.env; raises ConfigError if invalid."""
    try:
        return Settings()  # required values come from the environment / backend/.env
    except ValidationError as exc:
        raise ConfigError(describe_validation_error(exc)) from None
