# syntax=docker/dockerfile:1
# JustTheTwoOfUs API (FastAPI). Built and run by deploy/compose.yaml.
# Only the application, migrations and locked runtime dependencies go in:
# no tests, no test fakes, no dev tools, no .env.

FROM python:3.14-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Locked third-party dependencies only; the app itself runs from /app/app.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim-trixie
# A fixed, unprivileged user. Its group (10001) also reads the mounted secrets.
RUN groupadd --system --gid 10001 twoofus \
 && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin twoofus
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
# No package manager at runtime: pip (and the libraries it vendors) is unused
# by the app and only adds attack surface and scanner noise.
RUN python -m compileall -q app alembic \
 && python -m pip uninstall --yes --quiet pip \
 && rm -rf /usr/local/lib/python3.14/ensurepip
# hadolint ignore=DL3064
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TWOOFUS_ENV_FILE="" \
    TWOOFUS_SECRETS_DIR=/run/secrets
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status != 200)"]
# One worker on purpose: the now-playing cache, rate limits and single-flight
# locks live in this process. Trusted proxy addresses for
# X-Forwarded-For come from FORWARDED_ALLOW_IPS (set in deploy/compose.yaml).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--no-access-log", "--no-server-header", "--limit-concurrency", "64", \
     "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "10"]
