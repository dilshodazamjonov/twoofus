"""Logging setup with secret redaction.

Defence in depth: application code never logs tokens on purpose, but this
filter also scrubs anything that looks like a bearer token, OAuth code/state or
token field if a library or exception message happens to include one.
"""

from __future__ import annotations

import logging
import re
import sys

_PATTERNS = [
    (re.compile(r"(?i)(bearer|oauth)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)\b(access_token|refresh_token|id_token|code_verifier|device_code|client_secret"
            r"|code|state|token|password)(\"?\s*[:=]\s*\"?)[^\s&\"',}]+"
        ),
        r"\1\2[REDACTED]",
    ),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            # Render the traceback now and redact it, so secrets inside exception
            # messages never reach the handler.
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(formatted)
            record.exc_info = None
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # Third-party loggers: keep them quiet; their DEBUG output can include
    # request details we do not want in logs.
    for name in ("httpx", "httpcore", "yandex_music", "websockets", "aiohttp", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # We log requests ourselves without query strings (OAuth callbacks carry
    # authorization codes in the query), so uvicorn's access log stays off.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
