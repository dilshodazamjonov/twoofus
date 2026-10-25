"""Set a new password for a member and sign them out everywhere.

    uv run python -m app.cli.reset_password --username amira

There is deliberately no e-mail based recovery; whoever operates the server
resets passwords with this command. The password is prompted with getpass
(``--password-stdin`` for scripts) and never passed as an argument.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.auth.passwords import password_problem
from app.auth.sessions import revoke_all_sessions
from app.core.config import ConfigError, get_settings
from app.main import build_context, close_context
from app.models import User
from app.services.accounts import normalize_username


async def _reset(username: str, password: str) -> bool:
    ctx = build_context(get_settings())
    try:
        async with ctx.session_factory() as db:
            user = (
                await db.execute(select(User).where(User.username == normalize_username(username)))
            ).scalar_one_or_none()
            if user is None:
                return False
            user.password_hash = await ctx.passwords.hash(password)
            user.password_changed_at = ctx.clock()
            await revoke_all_sessions(db, ctx, user.id)
            await db.commit()
            return True
    finally:
        await close_context(ctx)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset a member's password.")
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin"
    )
    args = parser.parse_args(argv)
    try:
        get_settings()  # fail before asking for anything if .env is invalid
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("New password (min 10 characters): ")
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            return 2
    problem = password_problem(password, username=args.username)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    if not asyncio.run(_reset(args.username, password)):
        print("No such user.", file=sys.stderr)
        return 1
    print("Password updated; all of that member's sessions were signed out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
