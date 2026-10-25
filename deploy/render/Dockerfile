# syntax=docker/dockerfile:1
# One-container image for Render's free plan (render.yaml at the repo root);
# build context: the repo root. The Next.js server is the public origin on
# $PORT and proxies /api/* to FastAPI on 127.0.0.1:8000 with the proxy secret
# (frontend/src/proxy.ts). The database is external (Neon).

FROM node:24-trixie-slim AS web
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_OUTPUT=standalone \
    TWOOFUS_DEMO_UI=0 \
    BACKEND_INTERNAL_URL=http://127.0.0.1:8000
RUN rm -rf public/demo \
 && npm run build \
 && node scripts/check-bundle.mjs .next

FROM python:3.14-slim-trixie AS api
COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim-trixie
COPY --from=node:24-trixie-slim /usr/local/bin/node /usr/local/bin/node
RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin twoofus
WORKDIR /app
COPY --from=api /app/.venv ./.venv
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --from=web /app/.next/standalone ./web
COPY --from=web /app/.next/static ./web/.next/static
COPY --from=web /app/public ./web/public
COPY deploy/render/start.sh /usr/local/bin/twoofus-start
RUN python -m compileall -q app alembic
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TWOOFUS_ENV_FILE="" \
    ENVIRONMENT=production \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
USER 10001
CMD ["twoofus-start"]
