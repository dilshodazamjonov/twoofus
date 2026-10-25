"""Re-encrypt every stored secret with the first TOKEN_ENCRYPTION_KEYS key.

Key rotation:
  1. Generate a key:     uv run python -m app.cli.keys
  2. Put it FIRST:       TOKEN_ENCRYPTION_KEYS=<new>,<old>   and restart
  3. Re-encrypt:         uv run python -m app.cli.reencrypt          (or --dry-run)
  4. When it reports "0 could not be decrypted", drop <old> and restart.

Values are decrypted and encrypted in memory only and never printed. Rows that
cannot be decrypted with any configured key are counted and left untouched (the
app asks that person to reconnect when it next needs them).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import ConfigError, get_settings
from app.core.crypto import DecryptionError, TokenCipher
from app.main import build_context, close_context
from app.models import AuthFlowKind, ProviderAuthFlow, ProviderConnection
from app.services.credentials import flow_context, token_context


@dataclass
class Report:
    reencrypted: int = 0
    already_current: int = 0
    undecryptable: int = 0


def _rotate(cipher: TokenCipher, value: str | None, context: str, report: Report) -> str | None:
    if value is None:
        return None
    if not cipher.needs_reencryption(value):
        report.already_current += 1
        return value
    try:
        plaintext = cipher.decrypt(value, context=context)
    except DecryptionError:
        report.undecryptable += 1
        return value
    report.reencrypted += 1
    return cipher.encrypt(plaintext, context=context)


async def reencrypt_all(*, dry_run: bool) -> Report:
    ctx = build_context(get_settings())
    report = Report()
    try:
        async with ctx.session_factory() as db:
            connections = (await db.execute(select(ProviderConnection))).scalars().all()
            for conn in connections:
                for field, attr in (
                    ("access", "access_token_enc"),
                    ("refresh", "refresh_token_enc"),
                ):
                    current = getattr(conn, attr)
                    rotated = _rotate(
                        ctx.cipher,
                        current,
                        token_context(conn.user_id, conn.provider, field),
                        report,
                    )
                    if rotated != current:
                        setattr(conn, attr, rotated)
            flows = (
                (
                    await db.execute(
                        select(ProviderAuthFlow).where(ProviderAuthFlow.secret_enc.is_not(None))
                    )
                )
                .scalars()
                .all()
            )
            for flow in flows:
                field = (
                    "code_verifier" if flow.kind == AuthFlowKind.OAUTH_PKCE.value else "device_code"
                )
                flow.secret_enc = _rotate(
                    ctx.cipher, flow.secret_enc, flow_context(flow.id, field), report
                )
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
    finally:
        await close_context(ctx)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="count only, change nothing")
    args = parser.parse_args(argv)
    try:
        get_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    report = asyncio.run(reencrypt_all(dry_run=args.dry_run))
    verb = "would re-encrypt" if args.dry_run else "re-encrypted"
    print(
        f"{verb} {report.reencrypted} value(s); {report.already_current} already on the "
        f"current key; {report.undecryptable} could not be decrypted with any configured key"
    )
    if report.undecryptable:
        print(
            "Some values could not be decrypted: keep the old key(s) configured, or ask those "
            "members to reconnect their music service before removing an old key.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
