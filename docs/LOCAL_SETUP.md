# Local setup

You need no API keys to run Two of Us locally: the **Demo** provider works
offline. Spotify and Yandex are optional (see INTEGRATIONS.md).

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| uv | ≥ 0.5 (tested 0.12.11) | Creates `backend/.venv` and installs the locked Python deps. Install: https://docs.astral.sh/uv/getting-started/installation/ |
| Python | ≥ 3.12 (tested 3.12 and 3.14) | uv uses the version in `backend/.python-version` (3.14). It downloads it automatically if missing. |
| Node.js | ≥ 20.9 (tested 24.22.1 LTS) | **Linux/macOS/WSL:** `scripts/setup.sh` installs a checksum-verified copy into `.tools/node` if no native Node is found. No sudo, no profile changes. |
| Docker | optional | Only for running the test suite against PostgreSQL. |

> **WSL users:** the Windows `npm` (`/mnt/c/Program Files/nodejs/npm`) is often
> on the WSL PATH. Don't use it for this project: it installs Windows binaries
> that break Next.js on the Linux filesystem. The scripts use the project-local
> Node automatically. In an interactive shell, run `source scripts/env.sh`
> first, or install Node inside WSL (e.g. via nvm). One checkout = one OS:
> `backend/.venv` and `node_modules` are platform-specific.

## First-time setup

### Bash (Linux, macOS, WSL)

```bash
./scripts/setup.sh            # Node (if needed), backend/.venv, backend/.env, migrations, npm ci
cd backend && uv run python -m app.cli.bootstrap_owner && cd ..   # create YOUR account (password prompt)
./scripts/dev.sh              # FastAPI :8000 + Next.js :3000
```

Open **http://127.0.0.1:3000**. Don't use `localhost`: cookies are per-host,
and Spotify only accepts 127.0.0.1 loopback callbacks. There are equivalent
`make` targets: `make setup`, `make owner`, `make dev`, `make test`, `make smoke`.

### PowerShell (native Windows checkout, not WSL)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Setup
cd backend; uv run python -m app.cli.bootstrap_owner; cd ..
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

`scripts/dev.ps1` was syntax-checked with Windows PowerShell 5.1's parser but
has not been run end to end. The Bash path is the tested one.

### What setup creates

* `backend/.venv`: project-local Python environment (never install globally).
* `backend/.env`: copied from `.env.example`, with **fresh random**
  `SECRET_KEY` and `TOKEN_ENCRYPTION_KEYS`. Mode 600; never committed; never
  overwritten if it exists. Print new values any time with
  `uv run python -m app.cli.keys`.
* `backend/data/twoofus.db`: local SQLite database (gitignored).
* `frontend/node_modules`: installed with `npm ci` from `package-lock.json`.
  Dependency install scripts are blocked by npm 11; the single one present
  (`unrs-resolver`) is explicitly denied in `package.json → allowScripts`.

## Everyday commands

| Task | Command (from repo root) |
|---|---|
| Start everything | `./scripts/dev.sh` |
| Backend only | `cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --reload` |
| Frontend only | `source scripts/env.sh && cd frontend && npm run dev` |
| Apply migrations | `cd backend && uv run alembic upgrade head` |
| New migration | `cd backend && uv run alembic revision --autogenerate -m "..."` (review it!) |
| Create the owner | `cd backend && uv run python -m app.cli.bootstrap_owner` |
| Reset a password | `cd backend && uv run python -m app.cli.reset_password --username <name>` |
| All checks | `./scripts/test.sh` (`--build` adds `next build`, `--postgres` adds the PostgreSQL run) |
| End-to-end smoke | `./scripts/smoke.sh` (isolated ports 8100/3100, temp DB, Demo provider) |
| API docs (dev) | http://127.0.0.1:8000/api/v1/docs |

## Configuration reference (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `APP_NAME` | `Two of Us` | Shown in the UI and as the Yandex device name |
| `ENVIRONMENT` | `development` | `production` enforces https + secure cookies |
| `PUBLIC_APP_URL` | `http://127.0.0.1:3000` | Browser-facing origin; drives allowed Origin, cookie security, invite links |
| `EXTRA_ALLOWED_ORIGINS` | – | More origins allowed to POST (comma separated) |
| `DATABASE_URL` | SQLite in `backend/data/` | `postgresql+psycopg://…` in production (`postgres://` is accepted) |
| `SECRET_KEY` | **required** | ≥ 32 random chars; signs CSRF tokens |
| `TOKEN_ENCRYPTION_KEYS` | **required** | Comma-separated url-safe base64 32-byte keys; first one encrypts |
| `COOKIE_SECURE` | auto | Defaults to true when `PUBLIC_APP_URL` is https |
| `SESSION_TTL_DAYS` / `SESSION_IDLE_DAYS` / `SESSION_ROTATE_HOURS` | 30 / 14 / 24 | Session lifetime |
| `INVITE_TTL_HOURS` | 48 | Invitation lifetime (max 168) |
| `BOOTSTRAP_TOKEN` | empty | Enables `POST /api/v1/setup/owner` until an owner exists |
| `DEMO_MODE` | `true` in `.env.example` (code default `false`) | Enables the Demo provider |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_REDIRECT_URI` | empty | Enables Spotify (no client secret needed) |
| `YANDEX_ENABLED` | `true` | Enables the experimental Yandex adapter |
| `YANDEX_MUSIC_WEB_BASE` | `https://music.yandex.ru` | Base for track links |
| `NOW_PLAYING_TTL_SECONDS` | 20 | Upstream cache per connection (15–60) |
| `PROVIDER_TIMEOUT_SECONDS` | 8 | Per upstream call |
| `TWOOFUS_ENV_FILE` | (process env) | Use another env file; `""` ignores `backend/.env` (used by the smoke test) |

Frontend (`frontend/.env.local`, optional; see `frontend/.env.example`):
`BACKEND_INTERNAL_URL` (default `http://127.0.0.1:8000`). It is read by the
dev server and **baked in at `next build` time**.

## Testing against PostgreSQL locally

`./scripts/test.sh --postgres` starts a throwaway `postgres:18-alpine`
container on 127.0.0.1:55433 with a random password, runs the whole backend
suite against it, and removes it. Your own PostgreSQL server is not touched.
To use an existing **disposable** database instead:

```bash
cd backend
TWOOFUS_TEST_DATABASE_URL='postgresql+psycopg://user:pass@127.0.0.1:5432/twoofus_test' uv run pytest -q
```

The suite drops and recreates the `public` schema of that database for every
test. **Never point it at a database you care about.**

## Troubleshooting

| Symptom | Fix |
|---|---|
| Signed in, but Spotify says `session_mismatch` | You opened `localhost:3000` while the callback is on `127.0.0.1:3000`. Always use `http://127.0.0.1:3000`. |
| Backend refuses to start: `SECRET_KEY …` | `backend/.env` still has placeholders. Run `uv run python -m app.cli.keys --init-env` (if no `.env`), or paste values from `uv run python -m app.cli.keys`. |
| Backend refuses: `SPOTIFY_REDIRECT_URI …` | The URI must be `<PUBLIC_APP_URL>/api/v1/providers/spotify/callback`, not localhost. |
| Spotify card shows `provider_forbidden` | Add that Spotify user under Dashboard → User Management; the app owner needs Premium. |
| `next` fails with odd native-module errors in WSL | Windows npm was used. `rm -rf frontend/node_modules && source scripts/env.sh && cd frontend && npm ci`. |
| Port 3000/8000 already in use | Stop the other process, or run uvicorn/`next dev` with another port. Keep `PUBLIC_APP_URL` and the Spotify redirect in sync. |
| `/api/v1/ready` returns 503 `migrations: pending` | `cd backend && uv run alembic upgrade head` |
