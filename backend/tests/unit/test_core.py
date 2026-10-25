from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from app.auth.passwords import Passwords, password_problem
from app.core.config import Settings
from app.core.crypto import DecryptionError, TokenCipher, generate_key
from app.core.errors import RateLimited
from app.core.logging import RedactingFilter, redact
from app.core.ratelimit import Limit, RateLimiter
from app.core.security import CsrfSigner, hash_token, new_token, tokens_equal
from app.providers.urls import SPOTIFY_ARTWORK_HOSTS, SPOTIFY_LINK_HOSTS, safe_https_url
from tests.conftest import FAST_HASHER, make_settings


def _key() -> bytes:
    import base64

    raw = generate_key()
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


# ----- crypto -----------------------------------------------------------------------


def test_cipher_round_trip_and_ciphertext_is_not_plaintext() -> None:
    cipher = TokenCipher([_key()])
    sealed = cipher.encrypt("spotify-access-token", context="user:1:spotify:access")
    assert "spotify-access-token" not in sealed
    assert sealed.startswith("v1.")
    assert cipher.decrypt(sealed, context="user:1:spotify:access") == "spotify-access-token"


def test_cipher_rejects_wrong_context_tampering_and_unknown_key() -> None:
    cipher = TokenCipher([_key()])
    sealed = cipher.encrypt("secret", context="a")
    with pytest.raises(DecryptionError):
        cipher.decrypt(sealed, context="b")  # copied to another row/user/field
    head, body = sealed.rsplit(".", 1)
    flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
    with pytest.raises(DecryptionError):
        cipher.decrypt(f"{head}.{flipped}", context="a")
    with pytest.raises(DecryptionError):
        TokenCipher([_key()]).decrypt(sealed, context="a")
    with pytest.raises(DecryptionError):
        cipher.decrypt("garbage", context="a")


def test_cipher_key_rotation() -> None:
    old, new = _key(), _key()
    sealed_old = TokenCipher([old]).encrypt("token", context="c")
    rotated = TokenCipher([new, old])
    assert rotated.decrypt(sealed_old, context="c") == "token"
    assert rotated.needs_reencryption(sealed_old)
    assert not rotated.needs_reencryption(rotated.encrypt("token", context="c"))


def test_cipher_rejects_bad_keys() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        TokenCipher([b"short"])
    with pytest.raises(ValueError, match="at least one"):
        TokenCipher([])


# ----- tokens & CSRF ----------------------------------------------------------------


def test_tokens_and_hashes() -> None:
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) >= 43
    assert hash_token(a) == hash_token(a)
    assert len(hash_token(a)) == 64
    assert tokens_equal(a, a)
    assert not tokens_equal(a, b)


def test_csrf_tokens_are_bound_to_the_session() -> None:
    signer = CsrfSigner("k" * 40)
    token = signer.issue("session-1")
    assert signer.verify(token, "session-1")
    assert not signer.verify(token, "session-2")
    assert not signer.verify(token, "anon")
    assert not CsrfSigner("other-key" * 5).verify(token, "session-1")
    assert not signer.verify("no-dot", "session-1")
    assert not signer.verify("", "session-1")


# ----- configuration ----------------------------------------------------------------


def test_settings_reject_placeholders_and_short_secrets(tmp_path: object) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make_settings(
            "sqlite+aiosqlite:///x.db", secret_key="CHANGE_ME_please_change_me_now_1234567"
        )
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make_settings("sqlite+aiosqlite:///x.db", secret_key="short")
    with pytest.raises(ValidationError, match="TOKEN_ENCRYPTION_KEYS"):
        make_settings("sqlite+aiosqlite:///x.db", token_encryption_keys="CHANGE_ME")
    with pytest.raises(ValidationError, match="32 bytes"):
        make_settings("sqlite+aiosqlite:///x.db", token_encryption_keys="c2hvcnQ")


@pytest.mark.parametrize(
    ("redirect", "message"),
    [
        ("http://localhost:3000/api/v1/providers/spotify/callback", "localhost"),
        ("http://example.org/api/v1/providers/spotify/callback", "https"),
        ("http://127.0.0.1:3000/callback", "path must be exactly"),
        ("http://127.0.0.1:4000/api/v1/providers/spotify/callback", "same origin"),
    ],
)
def test_spotify_redirect_uri_rules(redirect: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        make_settings("sqlite+aiosqlite:///x.db", spotify_redirect_uri=redirect)


def test_spotify_client_id_requires_redirect() -> None:
    with pytest.raises(ValidationError, match="SPOTIFY_REDIRECT_URI is required"):
        make_settings("sqlite+aiosqlite:///x.db", spotify_redirect_uri="")


PRODUCTION = {
    "environment": "production",
    "public_app_url": "https://twoofus.example.net",
    "spotify_redirect_uri": "https://twoofus.example.net/api/v1/providers/spotify/callback",
    "demo_mode": False,
    "proxy_shared_secret": "p" * 16 + "R4nd0m-proxy-secret-value",
}


def test_production_requires_https_and_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="https"):
        make_settings("sqlite+aiosqlite:///x.db", environment="production", demo_mode=False)
    prod = make_settings("sqlite+aiosqlite:///x.db", **PRODUCTION)
    assert prod.secure_cookies is True
    assert prod.demo_controls_enabled is False
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        make_settings("sqlite+aiosqlite:///x.db", **{**PRODUCTION, "cookie_secure": False})


def test_production_refuses_demo_mode() -> None:
    # Invented songs must never be shown as real in a deployment.
    with pytest.raises(ValidationError, match="DEMO_MODE must be false in production"):
        make_settings("sqlite+aiosqlite:///x.db", **{**PRODUCTION, "demo_mode": True})
    development = make_settings("sqlite+aiosqlite:///x.db", demo_mode=True)
    assert development.demo_controls_enabled is True


def test_database_url_normalisation_and_derived_values() -> None:
    settings = make_settings("postgres://u:p@db:5432/twoofus")
    assert settings.database_url == "postgresql+psycopg://u:p@db:5432/twoofus"
    assert not settings.is_sqlite
    assert make_settings("sqlite:///a.db").database_url == "sqlite+aiosqlite:///a.db"
    local = make_settings(
        "sqlite+aiosqlite:///a.db", extra_allowed_origins="https://Other.example "
    )
    assert local.secure_cookies is False
    assert local.allowed_origins == {"http://127.0.0.1:3000", "https://other.example"}


def test_proxy_secret_validation_and_production_requirements() -> None:
    url = "sqlite+aiosqlite:///x.db"
    assert make_settings(url, proxy_shared_secret="").proxy_shared_secret is None
    with pytest.raises(ValidationError, match="PROXY_SHARED_SECRET"):
        make_settings(url, proxy_shared_secret="too-short")
    with pytest.raises(ValidationError, match="PROXY_SHARED_SECRET"):
        make_settings(url, proxy_shared_secret="CHANGE_ME" + "x" * 40)
    with pytest.raises(ValidationError, match="PROXY_SHARED_SECRET is required in production"):
        make_settings(url, **{**PRODUCTION, "proxy_shared_secret": ""})
    with pytest.raises(ValidationError, match="LOG_LEVEL=DEBUG"):
        make_settings(url, **{**PRODUCTION, "log_level": "DEBUG"})
    prod = make_settings(url, **PRODUCTION)
    assert prod.log_format == "json"
    assert make_settings(url).log_format == "text"
    assert make_settings(url, **{**PRODUCTION, "log_format": "text"}).log_format == "text"


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:8300",
        "http://example.com:8300",
        "http://10.0.0.5:8300",
        "http://127.0.0.1",
        "http://127.0.0.1:8300/path",
        "http://user:pw@127.0.0.1:8300",
        "http://127.0.0.1:8300?x=1",
    ],
)
def test_upstream_override_accepts_local_fakes_only(value: str) -> None:
    with pytest.raises(ValidationError, match="PROVIDER_UPSTREAM_OVERRIDE"):
        make_settings("sqlite+aiosqlite:///x.db", provider_upstream_override=value)


def test_upstream_override_is_refused_in_production() -> None:
    url = "sqlite+aiosqlite:///x.db"
    local = make_settings(url, provider_upstream_override="http://127.0.0.1:8300/")
    assert local.upstream_override == "http://127.0.0.1:8300"
    assert make_settings(url).upstream_override is None
    with pytest.raises(ValidationError, match="PROVIDER_UPSTREAM_OVERRIDE is for local tests"):
        make_settings(url, **{**PRODUCTION, "provider_upstream_override": "http://127.0.0.1:8300"})


def test_secrets_can_come_from_files(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    # Docker secrets / systemd credentials: one file per value, named after the setting.
    (tmp_path / "secret_key").write_text("f" * 8 + "ile-based-secret-key-value-123456\n")
    (tmp_path / "token_encryption_keys").write_text(generate_key())
    settings = Settings(_env_file=None, _secrets_dir=tmp_path)  # type: ignore[call-arg]
    assert settings.secret_key.get_secret_value() == "f" * 8 + "ile-based-secret-key-value-123456"
    monkeypatch.setenv("SECRET_KEY", "e" * 8 + "nv-wins-over-files-secret-value-1234")
    from_env = Settings(_env_file=None, _secrets_dir=tmp_path)  # type: ignore[call-arg]
    assert from_env.secret_key.get_secret_value().startswith("eeeeeeee")


# ----- passwords --------------------------------------------------------------------


async def test_passwords_hash_verify_and_unknown_user() -> None:
    passwords = Passwords(FAST_HASHER)
    hashed = await passwords.hash("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert await passwords.verify(hashed, "correct horse battery")
    assert not await passwords.verify(hashed, "wrong")
    assert not await passwords.verify(None, "anything")  # dummy verification path
    assert not await passwords.verify("not-a-hash", "anything")


def test_password_policy() -> None:
    assert password_problem("short", username="khaled")
    assert password_problem("khaled", username="khaled")
    assert password_problem("aaaaaaaaaaaa", username="khaled")
    assert password_problem("x" * 300, username="khaled")
    assert password_problem("a fine long passphrase", username="khaled") is None


# ----- rate limiting ----------------------------------------------------------------


def test_rate_limiter_forgets_idle_keys_within_a_day() -> None:
    # Keys contain client IP addresses: they must not linger in memory.
    now = [0.0]
    limiter = RateLimiter(monotonic=lambda: now[0])
    limiter.check("login:ip:203.0.113.7", Limit(attempts=5, window_seconds=900))
    assert limiter.tracked_keys() == 1
    now[0] += 24 * 3600 + 601
    limiter.check("login:ip:198.51.100.1", Limit(attempts=5, window_seconds=900))
    assert limiter.tracked_keys() == 1  # the idle key is gone, only the new one remains


def test_rate_limiter_window() -> None:
    now = [1000.0]
    limiter = RateLimiter(monotonic=lambda: now[0])
    limit = Limit(attempts=3, window_seconds=60)
    for _ in range(3):
        limiter.check("k", limit)
    with pytest.raises(RateLimited) as excinfo:
        limiter.check("k", limit)
    assert excinfo.value.headers == {"Retry-After": "60"}
    limiter.check("other", limit)  # keys are independent
    now[0] += 61
    limiter.check("k", limit)  # window slid


# ----- URLs & log redaction ---------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://i.scdn.co/image/abc", True),
        ("https://image-cdn-ak.spotifycdn.com/image/abc", True),
        ("http://i.scdn.co/image/abc", False),
        ("https://evil.example/i.scdn.co", False),
        ("https://i.scdn.co.evil.example/x", False),
        ("https://user:pw@i.scdn.co/x", False),
        ("https://i.scdn.co:8443/x", False),
        ("javascript:alert(1)", False),
        (None, False),
    ],
)
def test_artwork_url_allowlist(url: object, ok: bool) -> None:
    assert (safe_https_url(url, SPOTIFY_ARTWORK_HOSTS) is not None) is ok


def test_link_allowlist() -> None:
    assert safe_https_url("https://open.spotify.com/track/1", SPOTIFY_LINK_HOSTS)
    assert safe_https_url("https://spotify.evil/track/1", SPOTIFY_LINK_HOSTS) is None


def test_redaction() -> None:
    text = (
        "Authorization: Bearer abcdefghijklmnop refresh_token=SECRET1 "
        '{"access_token": "SECRET2"} /callback?code=SECRET3&state=SECRET4 password=hunter2'
    )
    cleaned = redact(text)
    for secret in ("abcdefghijklmnop", "SECRET1", "SECRET2", "SECRET3", "SECRET4", "hunter2"):
        assert secret not in cleaned


def test_redacting_filter_scrubs_records_and_tracebacks() -> None:
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, "token=%s", ("SUPERSECRET",), None)
    assert RedactingFilter().filter(record)
    assert "SUPERSECRET" not in record.getMessage()
    try:
        raise RuntimeError("access_token=LEAKED")
    except RuntimeError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    RedactingFilter().filter(record)
    assert record.exc_text is not None
    assert "LEAKED" not in record.exc_text


# ----- readable configuration errors ---------------------------------------------------


def test_config_errors_are_readable_and_never_echo_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import describe_validation_error

    secret = "do-not-print-me-" + "q" * 40
    with pytest.raises(ValidationError) as excinfo:
        make_settings("sqlite+aiosqlite:///x.db", secret_key=secret, spotify_redirect_uri="")
    assert secret not in str(excinfo.value)  # hide_input_in_errors
    assert describe_validation_error(excinfo.value) == (
        "Invalid configuration (backend/.env or environment variables):\n"
        "  - SPOTIFY_REDIRECT_URI is required when SPOTIFY_CLIENT_ID is set"
    )

    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError) as missing:
        Settings(_env_file=None, token_encryption_keys=generate_key())  # type: ignore[call-arg]
    assert "  - SECRET_KEY: Field required" in describe_validation_error(missing.value)


def test_get_settings_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    class IsolatedSettings(config.Settings):
        # Same settings class, but never reads the developer's backend/.env.
        model_config = SettingsConfigDict({**config.Settings.model_config, "env_file": None})

    secret = "s" * 48
    monkeypatch.setattr(config, "Settings", IsolatedSettings)
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", generate_key())
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(config.ConfigError) as excinfo:
            config.get_settings()
    finally:
        config.get_settings.cache_clear()
    message = str(excinfo.value)
    assert "SPOTIFY_REDIRECT_URI is required" in message
    assert secret not in message
    assert excinfo.value.__cause__ is None  # no chained pydantic traceback
