# Decisions

Short records of choices made in Phase 1: what, why, and what it costs.
Newest last.

### D1. Monorepo: Next.js frontend + FastAPI backend, one process each
Two deployables in one repo, no microservices or queue. Two people do not need
more, and fewer moving parts means fewer failure modes.

### D2. Same-origin `/api` proxy through Next.js rewrites (no CORS)
The browser talks only to the Next.js origin, and `/api/*` is rewritten to
FastAPI. Cookies are first-party (robust on iOS Safari and home-screen PWAs),
and the Spotify callback arrives with the session cookie.
* *Alternative:* a separate API domain with CORS + `SameSite=None` cookies.
  Rejected: third-party-cookie fragility on Safari, more CSRF surface.
* *Cost:* rewrites are fixed at build time, and Next.js passes through a
  client-supplied `X-Forwarded-For` (SECURITY.md #1).

### D3. Tooling: uv for Python, project-local Node in WSL
* `uv` manages `backend/.venv` and a hash-locked `uv.lock`. It was already
  installed here and gives one reproducible lock across platforms.
* This machine's WSL PATH exposed only the Windows npm, which breaks Next.js on
  the Linux filesystem, and there is no passwordless sudo. So
  `scripts/install-node.sh` puts a SHA-256-verified Node 24 LTS into `.tools/`
  (gitignored). The scripts prefer a native Node when one exists. No global
  changes.

### D4. Python 3.14 for development, supported from 3.12
* `requires-python >= 3.12`, as the prompt asked.
* The dev venv uses the system's 3.14.4. The full suite also passed on
  uv-managed CPython 3.12.
* SQLAlchemy 2.1, pydantic-settings and websockets 17 need ≥ 3.11 anyway.

### D5. Async SQLAlchemy 2 + Alembic; SQLite in development, PostgreSQL in production
* Drivers: aiosqlite (dev) and psycopg 3 (prod; it covers sync and async).
* Portable column types: `Uuid`, a `UTCDateTime` decorator because SQLite has
  no timezone support, and string enums with CHECK constraints instead of
  native enums.
* **Tested on both.** The entire suite passes on SQLite 3.46 and on PostgreSQL
  18.6 (Docker), including the migration round trip and a model-vs-migration
  drift check.

### D6. Server-side sessions, not JWTs
Opaque random tokens, stored hashed.
* Instant revocation (logout, password reset, account deletion), rotation and
  idle expiry are trivial.
* There is no token to leak via JavaScript, and no signing key that grants
  forging power.

### D7. CSRF: Origin allow-list + signed double-submit token bound to the session
Defence in depth on top of `SameSite=Lax`. Session binding stops a token
planted before login (or by a sibling origin) from working inside a session.
Login itself is CSRF-protected (anonymous binding), which blocks login CSRF.

### D8. Spotify: Authorization Code with PKCE, server-side, no client secret
* Spotify's first recommendation. Both PKCE and the confidential flow are
  documented as acceptable for a backend.
* The verifier never leaves the server, so intercepted codes are useless. No
  client secret has to be issued, stored or rotated.
* We did not combine a client secret with PKCE because Spotify does not
  document that combination.
* *Cost:* a refresh token can be redeemed with the public client id alone. It
  is encrypted at rest, and a full server compromise would expose a secret
  anyway.

### D9. Spotify scope: `user-read-currently-playing` only
The OpenAPI spec lists it as the endpoint's only required scope. We do not
request `user-read-playback-state` because nothing we built needs it.

### D10. Yandex: library device flow, polled by the frontend; no background tasks
* `request_device_code` on start; at most one `poll_device_token` per interval
  per poll request; the blocking `device_auth()` is never used.
* Nothing runs when nobody is looking, and the event loop is never blocked.
* The flow is bound to the app session.
* The refresh token is not stored: the library cannot use it, and unused
  secrets are a liability.

### D11. Yandex reads via Ynison `session()`, read-only, stable device id
* One short connection per fetch.
* Device title "Two of Us (read-only)" so she can recognise it.
* The device id is derived from our connection id (not the token), so repeated
  reads do not create new devices.
* No control methods are ever called.
* Track details come from `tracks([id])` without `init()`, which avoids
  account data.

### D12. Now-playing cache in memory only; request-driven polling
* A per-connection TTL of 20 s (bounded 15–60) is shared by both viewers.
* Single-flight lock, backoff honouring `Retry-After`, stale-but-flagged data
  for ≤ 5 min.
* No playback is written to the DB.
* *Cost:* one backend process only (fine for two users).
* *Alternative considered:* a DB cache table. Rejected because it persists
  third-party content and adds writes for nothing.

### D13. `last_changed_at` is observed, not taken from the provider
Set when this server first sees a different track or state, and `null` until
then. Spotify's `timestamp` field has not been verified live, and "unknown" is
better than a plausible-looking guess.

### D14. Non-music content is reported, but without details
Podcasts, ads, clips and generative streams appear as "playing something
non-music" (`content_type`, `detail_code=non_music_content`). The prompt is
about songs. Revealing podcast titles is a bigger privacy step, which a later
opt-in could add.

### D15. Consent: sharing is OFF by default and needs an acknowledged notice
* Turning sharing on requires the current `SHARING_NOTICE_VERSION`. The Phase 2
  UI shows the notice text.
* A non-sharing partner is answered `private` *before* any provider call. Even
  their service name is hidden.

### D16. One room per deployment, two members max, enforced by the database
* `rooms.singleton` is unique and must be 1.
* `room_members` primary key is `(room_id, slot)` with `slot IN (1,2)`.
* A partial unique index allows exactly one owner.

Race conditions therefore cannot produce a second room or a third member.
Tested: concurrent invitation accepts, on both databases.

### D17. One provider connection per user
Connecting a different service replaces the previous one after a successful
authorisation. Each card shows one source, so demo and real data never mix on
a card.

### D18. Owner bootstrap is CLI-first; web bootstrap only when explicitly enabled
* The CLI reads the password via getpass, or `--password-stdin` for
  automation; never argv.
* An unauthenticated "create the first admin" web endpoint invites instance
  takeover, so `POST /setup/owner` returns 404 unless `BOOTSTRAP_TOKEN` (≥ 32
  random characters) is set. It stops working the moment an owner exists.
  Useful for hosts without a shell.

### D19. Invitation links carry the token in the URL fragment
`/invite#token=…`. Fragments are never sent to servers, so the token stays out
of access logs and `Referer` headers. The page posts it to `/invitations/inspect`.

### D20. Deleting the owner promotes the partner
Deleting your account must not delete the other person's data. If the owner
leaves, the partner becomes owner, and can invite again or delete the room.

### D21. Frontend versions follow `create-next-app` 16.4.3's tested set
* Next 16.4.3, React 19.3.0, TypeScript 5.9, Tailwind 4, ESLint 9.
* ESLint stays on 9 even though npm marks 9.39.5 deprecated:
  `eslint-plugin-react` 7.37.5, `eslint-plugin-import` 2.32.0 and
  `eslint-plugin-jsx-a11y` 6.10.2 (the latest, used by `eslint-config-next`)
  declare peer support only up to ESLint 9.
* TypeScript 7 is not used for the same compatibility reason.

### D22. Errors are typed and stable
`{"error": {"code", "message"}}` everywhere, with `Retry-After` on 429.
Provider failures become playback `status` + `detail_code` instead of HTTP
errors, so one bad provider never breaks the other person's card.
