# Security and privacy

Two of Us holds very little, but what it holds is sensitive. That includes two
people's music-service grants and a live signal of what someone is doing right
now. The design goal is least data, least privilege, and explicit consent.

## Assets and threats considered

| Asset | Main threats | Controls |
|---|---|---|
| Provider tokens (Spotify, Yandex) | DB leak, backup leak, log leak, cross-user access | AES-256-GCM at rest, keys from env only; ciphertext bound to user + provider + field (AEAD associated data); never logged, never returned by any endpoint; deleted on disconnect or account deletion |
| Accounts | Password guessing, user enumeration, session theft or fixation | Argon2id; identical response and timing for unknown users; per-IP and per-username rate limits; random 256-bit session tokens stored hashed; HttpOnly + SameSite=Lax (+ `__Host-`/Secure on HTTPS) cookies; new session on every login; rotation every 24 h; idle (14 d) and absolute (30 d) expiry; logout revokes server-side |
| Room membership | Strangers joining, a third member | No signup; single-use, 48 h, hashed invitation tokens consumed atomically; DB caps: one room per deployment, two slots per room |
| Now-playing signal | Seen without consent; seen by a third party | Sharing is **off by default**; turning it on requires acknowledging the current sharing notice; a partner who is not sharing is never even queried; no history stored; consent switch takes effect on the next request |
| Partner's Yandex login | Credential phishing | Device flow on Yandex's own page; we never ask for, see or store her password; no third-party token sites |
| State-changing requests | CSRF, login CSRF, OAuth account-linking CSRF | Origin/Referer allow-list **and** signed double-submit token bound to the session; OAuth `state` hashed, single-use, 10 min, **bound to the starting session**; Yandex device flow bound to the session |

## Controls in detail

* **Passwords.** argon2-cffi `PasswordHasher` defaults (Argon2id, RFC 9106
  low-memory profile), with automatic rehash when parameters change. Hashing
  runs in a worker thread. The policy is ≥ 10 characters, not the username,
  not trivially repetitive.
* **Sessions.** The database stores SHA-256(token) only, so a DB leak does not
  reveal live cookies. No IP address or user agent is stored.
* **CSRF.** Every state-changing request needs both checks:
  * `Origin`/`Referer` must be `PUBLIC_APP_URL` (or `EXTRA_ALLOWED_ORIGINS`).
  * `X-CSRF-Token` must equal the `twoofus_csrf` cookie, and the HMAC must
    verify for the current session id.

  An anonymous token cannot be replayed inside a session (tested).
* **Authorisation.** Route dependencies distinguish 401 (not signed in) from
  403 (signed in, not allowed). No endpoint accepts a user or room id, so
  there is nothing to tamper with for IDOR. Tests check:
  * partners cannot use owner-only routes;
  * the partner's provider details are never visible to the other member;
  * the partner's service name is hidden while she is not sharing;
  * no response contains tokens.
* **Encryption at rest.** `TOKEN_ENCRYPTION_KEYS` holds one or more 32-byte
  keys; the first one encrypts. Ciphertext format: `v1.<key-id>.<nonce+ct>`.
  Tampering, a wrong key, or a ciphertext moved to another row or field all
  fail to decrypt. A credential that cannot be decrypted marks the connection
  `reauth_required`.
* **Logging.** Our request log records method, path, status and duration,
  never query strings (OAuth callbacks carry `code` and `state`). Uvicorn's
  access log is disabled. A redaction filter scrubs bearer tokens and
  `token=`/`code=`/`state=`/`password=` patterns from every log record and
  traceback. Third-party loggers (httpx, yandex_music, websockets, aiohttp) are
  set to WARNING. The smoke test greps the backend log for secrets.
* **Responses.** API responses carry `Cache-Control: no-store`, `nosniff`,
  `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and a deny-all CSP.
  Validation errors never echo submitted values. Artwork and link URLs are
  restricted to https on each provider's own hosts.
* **Rate limits (in memory, per process):**
  * login: 20 per IP / 15 min and 10 per username / 15 min;
  * invitation inspect/accept: 15 per IP / 15 min;
  * web bootstrap: 5 per IP / 15 min;
  * Spotify callback: 30 per IP / 15 min;
  * account deletion: 10 per user / 15 min.
* **Supply chain.**
  * Python deps are locked with hashes in `uv.lock`; `yandex-music` is pinned
    exactly.
  * npm deps are locked in `package-lock.json`.
  * npm 11's install-script blocking stays on; the only dependency with a
    script (`unrs-resolver`) is explicitly denied.
  * The Node toolchain download is SHA-256 verified against nodejs.org's
    `SHASUMS256.txt`.

## Data inventory

| Stored | Where | Retention |
|---|---|---|
| Username, display name, Argon2id hash | `users` | Until account deletion |
| Session hashes and timestamps | `auth_sessions` | Purged 7 days after expiry or revocation |
| Invitation hashes and timestamps | `invitations` | Purged 7 days after expiry, use or revocation |
| Sharing consent and acknowledged notice version | `share_preferences` | Until account deletion |
| Encrypted provider tokens, scopes, expiry; fetch/health timestamps and error codes | `provider_connections` | Until disconnect or account deletion |
| Pending authorisations (encrypted verifier/device code) | `provider_auth_flows` | Secret wiped on completion; row purged after 1 day |
| **Playback** (current track) | **process memory only**, ≤ 20 s (≤ 5 min as flagged stale) | Never written to disk |

**Not collected:** e-mail, IP addresses, user agents, device names, provider
account ids or profiles, listening history.

**Deletion.** `DELETE /api/v1/me` (password required) removes the user and,
via cascades, their sessions, credentials, pending flows, consent and the
invitations they created. If the owner leaves, the partner becomes owner. The
last member leaving deletes the room. Revoking the grant at the provider
itself is a separate step (see INTEGRATIONS.md).

## Secrets: generating and rotating

* **Generate.** `cd backend && uv run python -m app.cli.keys`, or
  `--init-env` to create `backend/.env`. Values come from `secrets` /
  `os.urandom`, locally. Never reuse dev secrets in production.
* **The app refuses to start** with placeholder, short or malformed secrets,
  a localhost Spotify redirect, or (in production) a non-https URL or
  insecure cookies.
* **Rotate `SECRET_KEY`.** Replace it and restart. Existing CSRF tokens become
  invalid; clients fetch new ones via `/auth/csrf` or `/auth/session`.
  Sessions are unaffected.
* **Rotate `TOKEN_ENCRYPTION_KEYS`.** Put the new key first and keep the old
  one after it (`NEW,OLD`). New writes use the new key, and old ciphertexts
  stay readable. Tokens are re-encrypted whenever they are refreshed or
  reconnected. Remove the old key only after every connection has been
  reconnected or refreshed. A bulk re-encrypt command is planned for Phase 3.
* **Never commit:**
  * `backend/.env`, `frontend/.env*` (except the examples);
  * `backend/data/`, any `*.db`;
  * `.venv`, `.tools/`.

  All are in `.gitignore`.

## Known limitations (to address in Phase 3 or accept knowingly)

1. **Client-supplied `X-Forwarded-For` is trusted behind the Next.js proxy.**
   Next.js only sets the header when it is absent, and the smoke test confirms
   a forged value reaches the per-IP limiter. Impact: per-IP limits can be
   evaded. Per-username limits, 256-bit invitation, session and state tokens,
   and ≥ 32-character bootstrap tokens remain effective.

   **Phase 3 fix:** put a TLS edge proxy in front that overwrites or appends
   `X-Forwarded-For`, and trust only that hop.
2. **Single process.** The rate limiter, now-playing cache and single-flight
   locks are per process. Run one uvicorn worker. Several workers weaken rate
   limits and multiply upstream calls, and Yandex reads could displace each
   other.
3. **Encryption keys live in the environment of the same server** that holds
   the database. Encryption at rest protects against DB/backup leaks, not
   against a full server compromise.
4. **The Yandex integration is unofficial.** It uses the Yandex Music Android
   app's public OAuth client (via the library). Accept the ToS ambiguity
   knowingly; it can stop working at any time.
5. **No MFA and no self-service password recovery.** The operator resets
   passwords with `app.cli.reset_password`, which also signs that member out
   everywhere.
6. **The frontend CSP and PWA headers are not set yet** (Phase 2/3). The API
   responses are covered.
