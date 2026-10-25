"""Generate secrets for backend/.env.

    uv run python -m app.cli.keys              # print fresh values
    uv run python -m app.cli.keys --init-env   # create backend/.env from .env.example

``--init-env`` never overwrites an existing .env. Values are random and local:
nothing is sent anywhere, and nothing is printed in --init-env mode.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys

from app.core.config import BACKEND_DIR
from app.core.crypto import generate_key

_GENERATED = {
    "SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "TOKEN_ENCRYPTION_KEYS": generate_key,
}


def init_env() -> int:
    example = BACKEND_DIR / ".env.example"
    target = BACKEND_DIR / ".env"
    if target.exists():
        print(f"{target} already exists; leaving it untouched.")
        return 0
    content = example.read_text(encoding="utf-8")
    for name, make in _GENERATED.items():
        content, count = re.subn(
            rf"^{name}=.*$", f"{name}={make()}", content, count=1, flags=re.MULTILINE
        )
        if count != 1:
            print(f"{name} missing from {example}", file=sys.stderr)
            return 1
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    print(f"Created {target} with freshly generated secrets (mode 600).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--init-env", action="store_true", help="create backend/.env if missing")
    args = parser.parse_args(argv)
    if args.init_env:
        return init_env()
    for name, make in _GENERATED.items():
        print(f"{name}={make()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
