"""Create the room owner. Run once, after migrations:

    uv run python -m app.cli.bootstrap_owner

The password is read with getpass (no echo, never a command-line argument).
For automation, ``--password-stdin`` reads it from standard input instead.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AppError
from app.main import build_context, close_context
from app.migrations_info import expected_head
from app.services import accounts


async def _create(username: str, display_name: str, password: str) -> str:
    ctx = build_context(get_settings())
    try:
        async with ctx.session_factory() as db:
            try:
                current = (
                    await db.execute(text("SELECT version_num FROM alembic_version"))
                ).scalar_one_or_none()
            except Exception:
                current = None
            if current != expected_head():
                raise SystemExit("The database is not migrated. Run: uv run alembic upgrade head")
            user = await accounts.create_owner(
                db, ctx, username=username, display_name=display_name, password=password
            )
            return user.username
    finally:
        await close_context(ctx)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create the single owner account.")
    parser.add_argument("--username", help="login name (3-32 chars: a-z 0-9 . _ -)")
    parser.add_argument("--display-name", help="name shown to your partner")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from stdin instead of prompting (for scripts)",
    )
    args = parser.parse_args(argv)

    username = args.username or input("Username: ").strip()
    display_name = args.display_name or input("Display name: ").strip()
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password (min 10 characters): ")
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            return 2

    try:
        created = asyncio.run(_create(username, display_name, password))
    except AppError as exc:
        print(f"Could not create the owner: {exc.message}", file=sys.stderr)
        return 1
    print(f"Owner '{created}' created. Sign in through the app, then invite your partner.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
