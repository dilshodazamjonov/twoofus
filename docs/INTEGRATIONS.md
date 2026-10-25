# Music integrations

Docs were checked on **2026-10-25**. "Verified" below means one of:
* checked against the official documentation or the official OpenAPI spec;
* checked by reading and testing the installed library's code.

**No live call to Spotify or Yandex has been made yet.** That needs your real
accounts and consent; see PHASE1_REPORT.md.

| Provider | Kind | Status in this app |
|---|---|---|
| Spotify | Official Web API | Implemented and tested against mocks; **live: unverified** |
| Yandex Music | **Unofficial**, reverse-engineered (`yandex-music` 3.2.2) | Implemented, tested against fakes and the library's real models; **experimental, live: unverified** |
| Demo | Built-in fake data | Implemented, tested end to end |

All adapters share one contract (`app/providers/base.py`). They report only
`playing`, `paused`, `idle` or `private`, plus track fields the provider
actually returned. Everything else comes from the service layer:
`not_connected`, `unavailable`, `error`, staleness and consent.

---

## Spotify (official Web API)

### Sources

* Current track endpoint: https://developer.spotify.com/documentation/web-api/reference/get-the-users-currently-playing-track
* OpenAPI spec (Spotify asks AI tools to use it instead of guessing): https://developer.spotify.com/reference/web-api/open-api-schema.yaml
* Authorization Code with PKCE: https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
* Refreshing tokens: https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens
* Redirect URI rules: https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
* Quota modes (development mode limits): https://developer.spotify.com/documentation/web-api/concepts/quota-modes
* Rate limits: https://developer.spotify.com/documentation/web-api/concepts/rate-limits
* Status codes / error objects: https://developer.spotify.com/documentation/web-api/concepts/api-calls
* Guidance for AI-written integrations: https://developer.spotify.com/documentation/web-api/tutorials/building-with-ai
* Design & branding (attribution): https://developer.spotify.com/documentation/design

### What we use

| Step | Request | Notes |
|---|---|---|
| Authorise | `GET https://accounts.spotify.com/authorize` | `response_type=code`, `code_challenge_method=S256`, `state` (256-bit, stored hashed, bound to the app session, 10-min expiry), `scope=user-read-currently-playing`, exact `redirect_uri`. |
| Exchange | `POST https://accounts.spotify.com/api/token` | `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `code_verifier`. **No client secret.** The verifier lives server-side, encrypted, and is wiped after use. |
| Refresh | same endpoint | `grant_type=refresh_token`, `refresh_token`, `client_id`. If no new refresh token is returned, the old one is kept (per the docs). |
| Read | `GET https://api.spotify.com/v1/me/player/currently-playing` | The only data endpoint called. No `market`, no `additional_types`. Podcasts and ads are reported only as "something non-music is playing". |

**Scope:** `user-read-currently-playing` only. The OpenAPI spec confirms it is
the security requirement of this endpoint. `user-read-playback-state` is not
requested because no tested feature needs it.

### Response handling

| Upstream | Result |
|---|---|
| `200` + track | `playing` / `paused` (from `is_playing`), with title, artists, album, artwork (smallest image ≥ 300 px, `*.scdn.co`/`*.spotifycdn.com` only), `open.spotify.com` link, duration, progress |
| `200` + `device.is_private_session: true` | `private`, no details |
| `200` + `item: null` / episode / ad | `content_type` episode/ad/other, `detail_code=non_music_content`, no details |
| `200` + local file | `local_track`: title/artists only, no link or artwork |
| `204` | `idle` (`nothing_playing`). The endpoint reference lists only 200/401/403/429; 204 handling follows the general status-code table ("succeeded but returns no message body"). |
| `401` | Refresh once, retry once; still 401 → `provider_reauth_required` (connection marked; the user must reconnect) |
| Token endpoint `invalid_grant` | `provider_reauth_required`. Refresh tokens **expire 6 months after authorisation**; the API exposes `reauthorize_by`. |
| Token endpoint `invalid_client` | `provider_not_configured` (wrong Client ID; re-auth would not help) |
| `403` | `provider_forbidden`, back off 10 min. The OpenAPI spec says re-authenticating will not help. In development mode this usually means the Spotify user is **not on the app's allowlist**, or the app owner lacks Premium. |
| `429` | `provider_rate_limited`, honouring `Retry-After` (default 30 s, max 1 h) |
| `429` with `reason: QUOTA_EXCEEDED` | `provider_quota_exceeded`, at least 5 min backoff |
| `5xx`, timeout, network error | `provider_unreachable`, exponential backoff 15 s → 5 min; last good state served as stale for ≤ 5 min |

### 2026 development-mode restrictions (from the quota-modes page)

* **The app owner must have Spotify Premium** for a development-mode app to work.
* **Up to 5 authenticated users**, each added to the app's allowlist. Two of
  you fit easily.
* Non-allowlisted users can log in but get **403** from the API.
* Development-mode apps have a **request quota**, separate from rate limits.
  Exceeding it returns 429 `QUOTA_EXCEEDED`. Our cache means at most about
  3 requests/minute per connected person while the app is open.
* Extended quota mode is only for organisations (≥ 250k MAU) since
  2025-05-15. **It is not available to this project, and not needed.**

### Setting up the Spotify app (you do this; it needs your Spotify login)

1. Go to https://developer.spotify.com/dashboard and log in with the Spotify
   account that will **own** the app. It must have **Premium**.
2. **Create app**:
   * Name, e.g. "Two of Us (private)". Description: a private two-person now-playing companion.
   * APIs used: **Web API**.
   * Redirect URIs: add **exactly** these:
     * Local: `http://127.0.0.1:3000/api/v1/providers/spotify/callback`
     * Production (Phase 3): `https://<your-domain>/api/v1/providers/spotify/callback`

     **Never use `localhost`** (Spotify rejects it). HTTPS is required except
     for loopback IPs.
   * Accept the Developer Terms.
3. **Settings → Basic information:** copy the **Client ID** into
   `backend/.env` as `SPOTIFY_CLIENT_ID`. Set `SPOTIFY_REDIRECT_URI` to the
   local URI above.
   * **The Client Secret is not needed**: the app uses PKCE. Don't copy it anywhere.
   * The backend refuses to start if the redirect URI is `localhost`, isn't
     https (except 127.0.0.1/[::1]), has a different path, or is on a different
     origin than `PUBLIC_APP_URL`.
4. **Settings → User Management:** add the name and Spotify e-mail of each
   person who will connect Spotify, including yourself if you're not the owner
   account.
5. Restart the backend. `GET /api/v1/config` should now show
   `providers.spotify.available: true`.

**Revoking access:** "Disconnect" in the app deletes our copy of the tokens.
To revoke the grant itself, remove the app at https://www.spotify.com/account/apps/.

### Terms and branding to respect (Phase 2 UI)

* Spotify metadata and artwork must be **attributed with the Spotify logo**
  (full logo where there's room) and must **link back to Spotify**. Suggested
  link text: "Open Spotify", "Play on Spotify" or "Listen on Spotify".
* Artwork must not be cropped, overlaid, blurred or animated. Round its corners
  4 px (small screens) / 8 px (large). Show metadata unaltered and legible;
  truncation is OK if the full text stays reachable.
* Developer Terms: no caching beyond immediate use. We hold playback in memory
  for ≤ 20 s (≤ 5 min when serving a flagged stale state) and never persist it.
* **Risk to review:** the "Browsing Spotify content" section says Spotify
  content "should never be seated next to content from similar services". That
  section is written for recommendation shelves, not playing views. Our design
  still places a Spotify card next to a Yandex card. For a private,
  non-commercial two-person app this looks low-risk, but it is your call. Keep
  the cards visually separate, each with its own attribution.

---

## Yandex Music (unofficial, experimental)

### Sources

* Library: https://github.com/MarshalX/yandex-music-api (README, `CHANGES.md`)
* Device-flow example: https://github.com/MarshalX/yandex-music-api/blob/main/docs/source/examples.device_auth.md
  (code in `examples/device_auth_async.py`)
* Ynison and token docs: https://ym.marshal.dev/ynison, https://ym.marshal.dev/token
* PyPI: https://pypi.org/project/yandex-music/ (3.2.2, released 2026-10-10)

**Version.** Pinned exactly to `yandex-music[async,ynison]==3.2.2`. A test fails
if another version is installed. Every upgrade must be re-checked against this
document.

### What is used, verified against the installed 3.2.2 code

* **Device authorisation** (`DeviceAuthMixin`, added in 3.0.0):
  * `ClientAsync().request_device_code(device_name="Two of Us")` →
    `POST https://oauth.yandex.ru/device/code`. Returns `device_code`,
    `user_code`, `verification_url`, `expires_in`, `interval`.
  * `ClientAsync().poll_device_token(device_code)` → one
    `POST https://oauth.yandex.ru/token`. Returns `None` while
    `authorization_pending`; raises `DeviceAuthError` for `slow_down`,
    `expired_token`, `access_denied` and similar. We map these to pending
    (+5 s interval), expired and denied.
  * We do **not** use the blocking `device_auth()` helper. The frontend calls
    `POST …/device-authorization/poll` every `interval` seconds. Each call makes
    **at most one** upstream request, and none if it arrives early, so FastAPI's
    event loop is never blocked waiting. The pending flow is bound to the app
    session, its device code is encrypted, and it expires per Yandex's
    `expires_in`.
* **Player state via Ynison, read-only.** `YnisonClientAsync(token,
  device_id=<stable per connection>, device_title="Two of Us (read-only)",
  max_reconnect_attempts=1).session(timeout=8)` reads one state frame and
  disconnects. Reading the library source shows the only message it sends is
  the standard handshake (`messages.build_full_state_request`). That handshake
  registers a **remote-control, non-player** device:
  * `can_be_player=False`
  * `is_currently_active=False`
  * empty queue
  * `DO_NOT_INTERCEPT_BY_DEFAULT`

  We never call `pause`, `resume`, `next_track`, `previous_track`, `set_volume`
  or `send`. **Server-side effect, unverified without a live account:** while a
  read is in progress (seconds), a device named "Two of Us (read-only)" may
  appear in her Yandex Music device list.
* **Track details:** `ClientAsync(token).tracks([track_id])` for title,
  artists, album and cover of the current track only. We **don't call
  `client.init()`**, which would fetch account details we don't need. Results
  are cached in memory per track id (6 h; 60 s after a failure). If the lookup
  fails, the card still shows Ynison's title and cover, with `artist_names: []`.
* **Mapping:**
  * No active device, or an offline one → `idle`.
  * `paused` → `paused`, otherwise `playing`.
  * Track link: `https://music.yandex.ru/album/<album>/track/<id>` (numeric ids only).
  * Covers: `avatars.yandex.net/...%%` → `400x400`, https, `*.yandex.net` only.
  * Video clips and generative streams → `other`, no details.

### Important facts to accept knowingly

* **Not an official API.** Yandex publishes none for this. The library warns
  that it is unofficial; it can break whenever Yandex changes things. All
  failures surface as `unavailable`/`error` with `experimental: true`, never as
  invented songs.
* **It signs in as the official Yandex Music Android app.** The device flow
  uses that app's public OAuth `client_id`/`client_secret`, embedded in the
  library. The token is therefore issued to that client, not to a registered
  "Two of Us" app, and Yandex has not approved this project. This is the
  library's documented default; there is no supported alternative for the
  Music API.
* **No password is ever shared.** Your partner opens the Yandex verification
  URL (shown in the app) on her own phone, signs in on **Yandex's own page**
  and enters the short code. We only receive the resulting token, which is
  encrypted at rest.
  * On iPhone the flow is plain Safari, so it is mobile-friendly. Whether
    Yandex accepts it from iOS Safari is **unverified** until she tries it.
  * If it fails on the phone, she can do the same steps on any computer while
    signed in to the app there. No third-party token website is ever needed or
    suggested.
* **No token refresh.** The library does not refresh tokens ("does not save it
  and does not refresh it after `expires_in`"). We store `expires_in` and ask
  her to approve again when the token expires or is rejected
  (`provider_reauth_required`). The refresh token is **not stored**, since we
  can't use it.
* **Revoking access:** "Disconnect" in the app deletes our copy of the token.
  To revoke it at Yandex, open her Yandex ID account settings (https://id.yandex.ru)
  and remove the device/app sign-in. The exact menu names were not verified
  here.
* **Licence:** the library is LGPL-3. Using it unmodified as a dependency does
  not change this app's licence.

---

## Demo provider

* `DEMO_MODE=true` (the default in `backend/.env.example`) enables
  `POST /api/v1/providers/demo/connect`. Set it to `false` in production.
* The songs are invented. The timeline cycles through playing, paused and idle
  deterministically, phase-shifted per connection.
* **Clearly labelled:** every response has `source: "demo"` and
  `is_demo: true`, there is no link-out, and artwork comes from
  `/demo/cover-N.svg`.
* A user has one connection at a time, so demo data can never mix with real
  data on the same card.

---

## Tested versions

Locked in `backend/uv.lock` and `frontend/package-lock.json`.

| Component | Version |
|---|---|
| Python (dev venv) | 3.14.4. The test suite also passes on CPython 3.12 (uv-managed). |
| fastapi / starlette / uvicorn | 0.162.0 / 1.10.0 / 0.54.0 |
| pydantic / pydantic-settings | 2.14.1 / 2.16.1 |
| sqlalchemy / alembic | 2.1.6 / 1.20.1 |
| aiosqlite / SQLite | 0.22.1 / 3.46.1 |
| psycopg (binary) / PostgreSQL | 3.3.6 / 18.6 (Docker `postgres:18-alpine`) |
| httpx / cryptography / argon2-cffi | 0.28.1 / 50.0.2 / 25.1.0 |
| yandex-music / websockets / betterproto / aiohttp | 3.2.2 / 17.3 / 1.2.5 / 3.14.5 |
| pytest / pytest-asyncio / respx / ruff / mypy | 9.1.1 / 1.4.0 / 0.23.1 / 0.17.2 / 2.4.0 |
| Node.js / npm | 24.22.1 LTS / 11.19.1 |
| next / react / react-dom | 16.4.3 / 19.3.0 / 19.3.0 |
| typescript / tailwindcss / eslint | 5.9.3 / 4.3.3 / 9.39.5 |
