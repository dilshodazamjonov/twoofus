# Architecture

Two of Us is a private now-playing companion for exactly two people. It is a
small monorepo: a Next.js app that the browser talks to, and a FastAPI backend
that holds all logic and data. Phase 1 built the backend, auth, provider
integrations and the proxy. The real interface and PWA arrive in Phase 2.

```
 iPhone Safari / desktop browser
            │  https://your-domain  (locally: http://127.0.0.1:3000)
            ▼
 ┌──────────────────────────────┐     /api/*  (rewrite, same origin)
 │ Next.js 16 (frontend/)       │ ───────────────────────────────┐
 │ pages, PWA shell (Phase 2)   │                                │
 └──────────────────────────────┘                                ▼
                                          ┌──────────────────────────────────┐
                                          │ FastAPI (backend/app)            │
                                          │  api/      HTTP routes + deps    │
                                          │  auth/     passwords, sessions   │
                                          │  services/ business rules        │
                                          │  providers/ Spotify|Yandex|Demo  │
                                          │  models/ db/  SQLAlchemy 2       │
                                          └───────┬───────────────┬──────────┘
                                                  │               │ HTTPS / WSS
                                     SQLite (dev) │               ▼
                                PostgreSQL (prod) ▼     api.spotify.com (official)
                                           ┌──────────┐ ynison.music.yandex.ru,
                                           │ database │ api.music.yandex.net,
                                           └──────────┘ oauth.yandex.ru (unofficial)
```

## Why a same-origin proxy

The browser only ever talks to the Next.js origin. `next.config.ts` rewrites
`/api/:path*` to FastAPI (`BACKEND_INTERNAL_URL`). Three things follow from that:

* **Cookies stay first-party.** Safari's tracking protection and iOS
  home-screen PWAs handle first-party `HttpOnly` cookies reliably, and
  `SameSite=Lax` works without CORS. CORS is not enabled at all.
* **The Spotify OAuth callback lands on the same origin as the session cookie.**
  The redirect URI is `<PUBLIC_APP_URL>/api/v1/providers/spotify/callback`. The
  browser sends the session cookie on that top-level navigation, and the
  backend checks that the session which started the flow is the one finishing it.
* **One URL to deploy and secure.**

Verified end to end by `scripts/smoke.sh`, which runs against a production
`next build`/`next start`:
* `Set-Cookie` attributes survive the proxy.
* The callback's cookie and state checks work.
* `303` redirects reach the browser.
* `DELETE` bodies pass through.

Two caveats:
* **Rewrites are fixed at build time.** They are compiled into
  `.next/routes-manifest.json`, so `BACKEND_INTERNAL_URL` must be set when
  running `next build`.
* **`X-Forwarded-For` can be spoofed.** Next.js only fills the header when it is
  missing, so a client can supply its own. See SECURITY.md.

## Backend layout

| Package | Responsibility |
|---|---|
| `app/main.py` | App factory. Builds the `AppContext` (settings, DB engine, cipher, providers, caches), middleware (security headers, query-free request log) and lifespan (hourly cleanup task). |
| `app/core/` | Settings and validation (`config.py`), AES-GCM token encryption (`crypto.py`), tokens and CSRF signing (`security.py`), rate limiter, errors, logging with secret redaction, clock. |
| `app/db/` | Declarative base with deterministic constraint names, async engine/session factory, `UTCDateTime` type. |
| `app/models/` | ORM tables (below). Imported by Alembic for migration drift checks. |
| `app/auth/` | Argon2id password hashing, server-side session lifecycle and cookies. |
| `app/services/` | Business rules: accounts and bootstrap, invitations, sharing consent, provider authorisation flows, the now-playing aggregation, cleanup. No HTTP here. |
| `app/providers/` | One adapter per music service behind a common contract (`base.py`). No database access here. |
| `app/api/` | FastAPI routers and dependencies only: authentication, owner checks, CSRF, input/output schemas. |
| `app/schemas/` | Pydantic v2 request/response models. Request bodies reject unknown fields. |
| `app/cli/` | `bootstrap_owner`, `reset_password`, `keys` (secret generation / `.env` creation). |
| `alembic/` | Migrations (async env; batch mode on SQLite). |

Data flows in one direction: routes → services → (DB | providers).
Providers never see the database. Refreshed credentials are returned to the
service layer, which encrypts and stores them.

## Data model

| Table | Purpose / key constraints |
|---|---|
| `users` | Username (stored lower-case, unique), display name, Argon2id hash. No e-mail is collected. |
| `rooms` | The one private space. `singleton` is unique and must equal 1, so a deployment can never hold more than one room, even if two bootstraps race. |
| `room_members` | Primary key is `(room_id, slot)` with `slot IN (1,2)`, so the database itself caps a room at two members. `user_id` is unique. A partial unique index allows one owner. |
| `invitations` | SHA-256 of the invitation token only; `expires_at`, `consumed_at`, `revoked_at`. |
| `auth_sessions` | SHA-256 of the session token; `expires_at` (absolute), `last_seen_at` (idle), `rotated_at`, `revoked_at`. No IP or user agent is stored. |
| `share_preferences` | `share_now_playing` (default **off**) and which sharing-notice version was acknowledged, and when. |
| `provider_connections` | One per user. Tokens are stored only as AES-256-GCM ciphertext bound to user, provider and field. Also health metadata: `last_fetch_at`, `last_success_at`, `last_error_code`, `backoff_until`, `consecutive_failures`, `reauth_required_at`, `authorized_at`. |
| `provider_auth_flows` | Pending Spotify PKCE / Yandex device-code authorisations, bound to the starting **session**. The verifier or device code is encrypted and wiped when the flow ends. |

There is **no table for playback or listening history**. A test asserts that no
column can hold track metadata.

## Now-playing pipeline

`GET /api/v1/room/now-playing` → `NowPlayingService.room_view`:

1. Load both members, their consent flag and their connection reference.
2. **Consent first.** If the partner is not sharing, the answer is
   `{"status": "private", "detail_code": "sharing_off"}`. Their provider is not
   called, and nothing about them is fetched or cached, not even which service
   they use. You always see your own card.
3. No connection gives `not_connected`. A connection needing re-auth gives
   `error` / `provider_reauth_required` with no upstream call.
4. Otherwise `playback_for(connection)`:
   * **Per-connection cache, TTL 15–60 s (default 20 s).** Shared by both
     members, so two people watching produce at most one upstream call per
     connection per TTL.
   * **Single flight.** An `asyncio.Lock` per connection with a re-check
     inside, so simultaneous requests wait for one fetch.
   * **Backoff.** After a failure, no upstream calls until `backoff_until`:
     `Retry-After`/`go_away` when the provider supplies one, otherwise
     exponential from 15 s to 5 min.
   * **Stale data.** During backoff the last good state is served for at most
     5 minutes, with `is_stale=true`, `progress_ms=null` and a `detail_code`
     saying why. After that it becomes `unavailable` or `error`.
5. The two members are fetched concurrently (`asyncio.gather`).

The cache lives **in process memory only**. Playback content never touches the
database or disk, which also keeps us inside Spotify's "no caching beyond
immediate use" rule. The trade-off: run **one backend process** (one uvicorn
worker), which is ample for two people. Several processes would each poll
separately, and Ynison connections from two processes would displace each
other.

**Polling contract for the frontend (Phase 2):**
* Poll `now-playing` every `poll_after_seconds`, and only while the app is
  visible.
* Interpolate progress locally from `fetched_at` + `progress_ms` while
  `is_playing` is true.
* Background refresh on iPhone is not promised. iOS suspends PWAs, and neither
  provider offers push for this.

### Playback contract

| Field | Meaning |
|---|---|
| `source` | `spotify` / `yandex` / `demo`. `null` when the partner is not sharing. |
| `status` | `playing`, `paused`, `idle`, `not_connected`, `private`, `unavailable` (temporary, e.g. rate-limited or unreachable), `error` (action needed, e.g. reconnect, allowlist). |
| `detail_code` | Machine reason, e.g. `sharing_off`, `nothing_playing`, `provider_private_session`, `non_music_content`, `incomplete_metadata`, `provider_reauth_required`, `provider_forbidden`, `provider_rate_limited`, `provider_quota_exceeded`, `provider_unreachable`, `provider_bad_response`, `provider_not_configured`. |
| `content_type` | `track`, `local_track`, `episode`, `ad`, `other`. Episodes and ads are reported as "something is playing" without details. |
| `track_title`, `artist_names`, `album`, `artwork_url`, `track_url`, `duration_ms` | Only what the provider actually supplied. Unknown values are `null` or `[]`, never invented. Artwork and link URLs are restricted to https on each provider's own hosts. |
| `progress_ms` | Position at `fetched_at`. `null` when unknown or stale. |
| `is_playing` | `true` / `false`, or `null` when unknown. Paused is not playing. |
| `fetched_at` | When the provider was actually asked. |
| `last_changed_at` | When this server first saw the current track or state. `null` until a change has been observed (unknown is not "now"). |
| `is_stale`, `is_demo`, `experimental` | Freshness flag, DEMO label, unofficial-integration flag (Yandex). |

## Authentication and authorisation

* **Accounts.** Invite-only. The owner is created by CLI (or by a one-time,
  token-gated endpoint if `BOOTSTRAP_TOKEN` is set). The owner issues one
  48-hour single-use invitation, consumed atomically with
  `UPDATE … WHERE pending … RETURNING` in the same transaction as the partner
  insert.
* **Sessions.** Random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie
  (`__Host-` prefixed and `Secure` on HTTPS). Only the SHA-256 is stored.
  * 30-day absolute and 14-day idle expiry, token rotation every 24 h.
  * Every login creates a new session and revokes the previous one, which
    prevents session fixation.
* **CSRF.** Every state-changing request needs both:
  * an `Origin` (or `Referer`) in the allow-list;
  * an `X-CSRF-Token` header equal to the `twoofus_csrf` cookie, HMAC-signed
    and bound to the current session id (`anon` before login).
* **Status codes.** `401 not_authenticated` / `session_expired` mean "not
  signed in". `403` means signed in but not allowed: `owner_only`,
  `csrf_failed`, `wrong_password`. No endpoint takes a user or room id, so
  there is no object id to tamper with. Everything is derived from the session.

## API (all under `/api/v1`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | – | Liveness |
| GET | `/ready` | – | Database reachable and migrations at head (503 otherwise) |
| GET | `/config` | – | Public capabilities: app name, available providers, TTL, sharing-notice version. No secrets. |
| GET | `/setup/status` | – | Does an owner exist / is web bootstrap enabled |
| POST | `/setup/owner` | bootstrap token | One-time owner creation (404 unless `BOOTSTRAP_TOKEN` is set) |
| GET | `/auth/csrf` | – | Issue a CSRF token and cookie |
| GET | `/auth/session` | – | Current user/session (+ CSRF token) |
| POST | `/auth/login` | – | Sign in (rate-limited per IP and per username) |
| POST | `/auth/logout` | session | Revoke the session |
| POST | `/invitations` | owner | Create the invitation (token shown once; link carries it in the URL `#fragment`) |
| GET / DELETE | `/invitations/current` | owner | Pending invitation status / revoke |
| POST | `/invitations/inspect` | – | Check a token; returns inviter display name (rate-limited) |
| POST | `/invitations/accept` | – | Create the partner account and sign in (rate-limited) |
| GET / PATCH / DELETE | `/me` | session | Profile / rename / delete account (password required) |
| GET / PUT | `/me/sharing` | session | Consent switch; turning on requires the current notice version |
| GET | `/room` | session | Members (partner's provider hidden unless sharing; invitation state for the owner) |
| GET | `/room/now-playing` | session | The two-person view |
| GET | `/providers` | session | Available services, *my* connection health, pending authorisation |
| DELETE | `/providers/connection` | session | Disconnect and delete stored credentials |
| POST | `/providers/spotify/authorize` | session | Start Spotify PKCE; returns `authorization_url` |
| GET | `/providers/spotify/callback` | (session cookie) | OAuth redirect target; 303 to `/?connect=spotify&result=…` |
| POST / DELETE | `/providers/yandex/device-authorization` | session | Start / cancel Yandex device flow |
| POST | `/providers/yandex/device-authorization/poll` | session | At most one upstream check per interval |
| POST | `/providers/demo/connect` | session | Use the DEMO provider (only if `DEMO_MODE=true`) |

Errors always look like `{"error": {"code": "...", "message": "..."}}`.
Validation errors add `details`, without echoing submitted values. Interactive
OpenAPI docs are at `/api/v1/docs` outside production. The document validates
with `openapi-spec-validator` (OpenAPI 3.1.0).

## What is deliberately not here

* No listening history
* No audio streaming or playback control
* No background polling when nobody has the app open
* No public pages, profiles or search
* No e-mail collection or e-mail password reset (use `app.cli.reset_password`)
* No microservices or queue
