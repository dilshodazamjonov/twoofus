# Phase 1 report: foundation, backend, auth, music integrations

Date: 2026-10-25 · Environment: Windows + WSL2 (Ubuntu 26.04.1), bash.
Phase 2 (romantic UI + PWA) and Phase 3 (hardening + deployment) are **not
started**.

## (a) Files and architecture created

```
TwoOfUs/
├─ backend/                      FastAPI app (Python ≥3.12; dev venv 3.14.4 at backend/.venv)
│  ├─ app/
│  │  ├─ api/      routes: system, auth+setup, invitations, me, room, providers; deps (auth, owner, CSRF)
│  │  ├─ auth/     Argon2id passwords, server-side sessions + cookies
│  │  ├─ core/     settings validation, AES-256-GCM token cipher, CSRF signer, rate limiter, errors, log redaction
│  │  ├─ db/ models/ schemas/   SQLAlchemy 2 async models, Pydantic v2 schemas
│  │  ├─ services/ accounts/bootstrap, invitations, sharing consent, provider auth flows, now-playing, cleanup
│  │  ├─ providers/ base contract + spotify.py (official), yandex.py (unofficial, experimental), demo.py
│  │  └─ cli/      bootstrap_owner, reset_password, keys
│  ├─ alembic/     async env + migration 0001 (hand-reviewed)
│  ├─ tests/       unit/ + integration/ (146 tests, no real credentials)
│  ├─ pyproject.toml, uv.lock, .python-version, .env.example, alembic.ini
├─ frontend/                     Next.js 16.4.3 + React 19.3 + TS strict + Tailwind 4; package-lock.json
│  ├─ next.config.ts             same-origin /api/* → FastAPI rewrite
│  ├─ src/app/                   Phase-1 status page (real UI = Phase 2)
│  └─ public/demo/               abstract DEMO cover art
├─ docs/  ARCHITECTURE, INTEGRATIONS, LOCAL_SETUP, SECURITY, DECISIONS, PHASE1_REPORT
├─ scripts/ setup.sh, dev.sh, test.sh, smoke.sh + smoke_test.py, install-node.sh, env.sh, dev.ps1
└─ Makefile, .gitignore, .gitattributes, .editorconfig
```

**Architecture in short:**
* **Proxy.** The browser talks only to Next.js; `/api/*` is proxied to
  FastAPI, so cookies are first-party and the Spotify callback shares the
  session's origin.
* **Layers.** Routes → services → (database | provider adapters).
* **Data.** Seven tables, with no playback/history table. One room per
  deployment and at most two members, both enforced by DB constraints.
* **Now-playing.** Consent filter before any provider call; per-connection
  20 s in-memory cache shared by both viewers; single flight; backoff honouring
  `Retry-After`; stale data flagged and dropped after 5 min.

Details: ARCHITECTURE.md, DECISIONS.md.

**Local state created on this machine (not committed):**
* `.tools/node` (Node 24.22.1 LTS)
* `backend/.venv`
* `backend/.env` with freshly generated `SECRET_KEY`/`TOKEN_ENCRYPTION_KEYS` (mode 600)
* `backend/data/twoofus.db` (migrated, **no users**: you create the owner yourself)

## (b) Commands run and results

| Check | Command | Result |
|---|---|---|
| Lint + format | `uv run ruff check . && uv run ruff format --check .` | pass (78 files) |
| Types | `uv run mypy` (strict, pydantic plugin) | pass (60 source files) |
| Tests, SQLite | `uv run pytest -W error::ResourceWarning --cov=app` | **146 passed**, 93% branch coverage |
| Tests, PostgreSQL 18.6 | `./scripts/test.sh --postgres` (throwaway Docker container) | **146 passed** |
| Tests, Python 3.12 | uv-managed CPython 3.12.14 in a scratch venv (not backend/.venv) | **146 passed** |
| Migrations | upgrade → `alembic check` → downgrade base → upgrade | pass; no drift (also asserted in tests on both DBs) |
| OpenAPI | `openapi-spec-validator` 0.9.0 on `/api/v1/openapi.json` | valid OpenAPI 3.1.0, 24 paths |
| Frontend | `npm run lint`, `npm run typecheck`, `npm run build` | pass (Next 16.4.3, Turbopack) |
| Setup | `./scripts/setup.sh` | pass (created `.env`, migrated, `npm ci`) |
| Dev servers | `./scripts/dev.sh` + curl via `127.0.0.1:3000` | health/ready/config OK through the proxy |
| **E2E smoke** | `./scripts/smoke.sh` (production `next build`/`start` proxy → uvicorn, isolated DB, DEMO) | **29/29 checks pass** (list below) + backend log contains no codes/state/passwords |
| PowerShell | Windows PowerShell 5.1 parser on `scripts/dev.ps1` | 0 syntax errors (**not executed**) |
| All-in-one | `./scripts/test.sh --build --postgres` | "All checks passed." |

What the smoke test covers, all through the real Next.js proxy:
* Owner created by the CLI.
* Login rejected without a CSRF token, then accepted with one.
* `HttpOnly`/`SameSite=Lax` cookie forwarded; security headers intact.
* DEMO connected; now-playing labelled `is_demo`.
* Invitation created (token in the URL fragment), inspected, accepted, and
  re-use rejected.
* Consent: `private` until sharing is on; visible after; hidden again
  immediately when turned off.
* Spotify authorize URL (PKCE S256, minimal scope, exact redirect).
* Callback: a different session is refused; the session cookie arrives and
  state is accepted; a 303 lands on a page that renders.
* No token or password in any response.
* Logout gives 401; account deletion via `DELETE` with a body works through
  the proxy.

**Warnings seen (non-blocking):**
* npm marks ESLint 9.39.5 deprecated. It is kept because the Next ESLint
  plugins cap their peer range at ESLint 9 (D21).
* `stringcase` (a dependency of `betterproto`, used by the Yandex library)
  emits a Python `SyntaxWarning` about an invalid escape sequence.

## (c) Confirmed vs mocked/unverified provider functionality

| Capability | Status |
|---|---|
| **Demo provider** (end to end, through the proxy) | ✅ Confirmed working |
| App auth, sessions, CSRF, invitations, consent, IDOR boundaries, deletion | ✅ Confirmed (tests + smoke) |
| Spotify: authorize URL, state/session binding, callback redirects, error/denial paths | ✅ Confirmed locally (no Spotify contact needed) |
| Spotify: code exchange, refresh, currently-playing parsing, 204/401/403/429/5xx/timeout handling | 🧪 Tested against **mocked** HTTP built from the official docs and OpenAPI spec. **Live: unverified.** |
| Yandex: device-flow start/poll/slow_down/denied/expired, Ynison state mapping, track metadata, error mapping | 🧪 Tested with a fake gateway **and** the installed `yandex-music` 3.2.2 model/exception classes. **Live: unverified. Experimental, unofficial.** |
| Yandex: read-only claim | 🔍 Verified by reading the library source: only the standard non-player handshake is sent. The server-side effect of a brief read-only device appearing is unverified. |
| Yandex device flow from iPhone Safari | ❓ Unverified until your partner tries it (fallback: do the same on a computer) |

## (d) What you must obtain, and from where

| Item | Needed? | Where / how |
|---|---|---|
| App secrets (`SECRET_KEY`, `TOKEN_ENCRYPTION_KEYS`) | Yes; **already generated locally** in `backend/.env` | For production, generate **new** ones: `cd backend && uv run python -m app.cli.keys`. Never reuse dev values. |
| Spotify **Client ID** | Only if you want Spotify | 1. Log in at https://developer.spotify.com/dashboard with the account that will own the app. **It must have Spotify Premium** (2026 development-mode rule). 2. Create app → APIs used: **Web API**. 3. Redirect URIs (exact): `http://127.0.0.1:3000/api/v1/providers/spotify/callback` now; `https://<your-domain>/api/v1/providers/spotify/callback` in Phase 3. **Never localhost.** 4. Settings → copy **Client ID** into `backend/.env` as `SPOTIFY_CLIENT_ID=…`, and set `SPOTIFY_REDIRECT_URI` to the local URI. 5. Settings → **User Management**: add the name and Spotify e-mail of each person who will connect Spotify (max 5 in development mode). 6. Restart the backend. |
| Spotify **Client Secret** | **No.** The app uses PKCE | Don't copy it anywhere. |
| Spotify extended quota | **No** (organisations with ≥ 250k MAU only) | Development mode is enough for two people. |
| Yandex API key / developer app | **No API key exists or is needed** | Your partner connects in the app: she opens the Yandex link shown (on Yandex's own site), signs in there, and enters the code. **Her password is never shared.** Read INTEGRATIONS.md → "Important facts" with her first (unofficial client, Android-app OAuth client, may break). |
| Demo provider | **No key needed** | `DEMO_MODE=true` (default in `.env.example`). Set `false` in production. |
| Apple Developer Program / App Store | **No** | iPhone uses Safari → Share → Add to Home Screen (Phase 2 builds the PWA). |

## (e) Starting locally

```bash
./scripts/setup.sh                                                  # once (already done here)
cd backend && uv run python -m app.cli.bootstrap_owner && cd ..     # once: create YOUR account
./scripts/dev.sh                                                    # then open http://127.0.0.1:3000
```

PowerShell (native Windows checkout): `scripts\dev.ps1 -Setup`, then
`scripts\dev.ps1`. API docs: http://127.0.0.1:8000/api/v1/docs.
Checks: `./scripts/test.sh [--build] [--postgres]`, `./scripts/smoke.sh`.

To try the two-person flow before Phase 2 (no UI yet), use the API docs page:
1. Log in, `POST /api/v1/providers/demo/connect`, `POST /api/v1/invitations`.
2. In a private window, accept the invitation.
3. Set `PUT /me/sharing`, then compare `GET /api/v1/room/now-playing` from both
   sides.

## (f) Known risks and next-phase readiness

**Risks:**
1. **The Yandex integration is unofficial.** It uses the Yandex Music Android
   app's public OAuth client via the library, can break without notice, and
   cannot refresh tokens. It is marked experimental everywhere.
2. **Spotify development-mode rules:** Premium owner, allowlisted users,
   request quota; Spotify can change them. Live behaviour (including the 204
   case and private sessions) is still unverified.
3. **Spotify branding rules** need care in Phase 2: logo attribution, uncropped
   artwork, link back, and the "not next to similar services" clause. See
   INTEGRATIONS.md.
4. **`X-Forwarded-For` spoofing** behind the Next.js proxy weakens per-IP rate
   limits. It needs a TLS edge proxy in Phase 3.
5. **Single-process design.** In-memory cache, locks and rate limits mean one
   uvicorn worker.
6. **iOS PWAs don't run in the background.** Updates arrive only while the app
   is open (by design, not promised otherwise).
7. **The `betterproto` → `stringcase` chain is old.** Its `SyntaxWarning` could
   become an error in a future Python release, breaking Ynison imports.

**Ready for Phase 2:**
* Stable `/api/v1` contract with a validated OpenAPI 3.1 schema.
* CSRF/session flow documented for the frontend: fetch `/auth/session`, send
  `X-CSRF-Token`, expect 401 `session_expired`.
* `poll_after_seconds` and the playback contract (statuses, `detail_code`,
  `is_stale`, `is_demo`, `experimental`).
* Sharing-notice versioning; invite links at `/invite#token=…`; Spotify
  results at `/?connect=spotify&result=…`; demo artwork in `/demo/`.

**Not built (explicitly out of Phase 1):**
* All real UI and the PWA manifest/service worker.
* The **heart interaction**, which will need a small backend endpoint in
  Phase 2.
* Deployment, frontend CSP, bulk key re-encryption.
