# Integration and Security Boundaries

Start with the [complete quick integration](quickstart.md). To explore the components first, install `ChatLogin[demo]` and run `chatlogin serve`; see [Demo](demo.md).

## Choose an Integration Level

| Requirement | Entry point | Host responsibilities |
| --- | --- | --- |
| Ready-to-use login page | `FastAPIAuth(..., ui=LoginUI(...))` | User source, business routes, deployment and TLS |
| Custom brand or layout | `LoginUI(template_dirs=..., template_name=...)` or `renderer` | Custom HTML/CSS and renderer safety |
| Existing HTML/JS frontend | `FastAPIAuth(..., ui=None)` | Existing page, frontend state, all business data |
| Existing HTTP/database contract | `CallbackBackend`, `SessionManager`, host `SessionStore` | Stable account IDs, password data, session mapping and response compatibility |
| Standard-library HTTP page | `LoginUI(...).render(context)` + `ChatLogin[ui]` | HTTP handler, cookies, Origin/CSRF and response fields |

Headless does not require another auth microservice. Mount JSON routes in the existing FastAPI process, or call the core Python API while keeping existing HTTP handlers and response fields. Python packages can carry HTML/CSS/JS; host templates take priority over package templates, without editing site-packages.

## Choose an Authentication Backend {#backends}

| Account source | Entry point | Responsibility |
| --- | --- | --- |
| Fixed account / multiple accounts | `PasswordBackend(accounts)` | One / multiple explicit `Principal` and `PasswordHash` entries, with a chosen `SessionStore` |
| Other host user database | `CallbackBackend(authenticate)` + host `SessionStore` | Host verification and mapping; do not assume the ChatVoice schema |
| Async upstream service | `AsyncCallbackBackend(authenticate)` + `SessionManager` | Await host verification; invalid input is not sent upstream and invalid results fail closed |
| Existing ChatVoice accounts and sessions | `ChatVoiceAuth` | Ready-made, opt-in compatibility backend; no ChatVoice or `web` dependency |

`CallbackBackend` and `AsyncCallbackBackend` share the same input bounds: usernames are 1..256 UTF-8 bytes and passwords are 1..1024 UTF-8 bytes. Results must be an authenticated `Principal` or `None`; do not place private upstream Authorization, model keys, Dufs/Overleaf credentials or relay context into `Principal` metadata, session JSON or UI payloads.

### ChatVoice Schema Compatibility Backend

```python
from chatlogin.backends import ChatVoiceAuth

# host is the application object. Resolve its current connection, lock and clock
# on each call instead of capturing a database path.
auth = ChatVoiceAuth(
    lambda: host.open_auth_connection(),
    lambda: host.auth_lock,
    lambda: host.utc_now().timestamp(),
    ttl=86400,
)
# Existing HTTP handlers can call:
# auth.login(account, password) -> IssuedSession | None
# auth.resolve_row(token) -> dict | None
# auth.check_csrf(auth_row, submitted) -> None; raises AccessDenied on failure
# auth.logout(token) -> None
```

The factory must return a fresh `sqlite3.Connection` with `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON` and no pending transaction; each operation closes it. The host owns initialization of the existing schema, file permissions and account creation:

- `accounts(id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at TEXT NOT NULL)`.
- `auth_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)`, with a foreign key from `user_id` to `accounts(id) ON DELETE CASCADE`.

This is **ChatVoice schema compatibility**, not a generic ORM for arbitrary SQLite account systems. Account matching is exact; retain host case/whitespace normalization before calling. Passwords keep PBKDF2-HMAC-SHA256 at 310000 iterations and existing salt/digest material. Account IDs, ISO expiry (including offsets), legacy 32-character CSRF and SHA-256 token digests are preserved. Anonymous, expired and invalid requests create no identity. Resolution rejoins the account instead of caching a user snapshot.

`ChatVoiceSessionStore(connect, lock, clock, *, max_sessions=10000)` accepts only the `chatvoice` namespace and `Role.USER` sessions, never guest/admin. Capacity is database-wide and SQLite transactions serialize it across store instances. Live sessions are not evicted; a full store raises `StoreFull`. `SessionManager.issue(..., previous_token=...)` replaces atomically, rolling back to the old session on insert failure. `ChatVoiceAuth` preserves existing constructor calls and adds optional keyword `max_sessions=10000`; the store and manager can also be composed separately.

### Compose with All Three UI Modes

With `ChatLogin[web]`, pass a sync or async backend and its manager to the generic adapter:

```python
from chatlogin.fastapi import FastAPIAuth
from chatlogin.ui import LoginUI

web = FastAPIAuth(auth.backend, auth.manager, origin="https://example.test",
                 ui=LoginUI())  # default UI
# ui=LoginUI(template_dirs=("templates",), template_name="host/login.html")  # host override
# ui=None  # headless JSON; or use the Python methods above with existing HTTP handlers
app.include_router(web.router)
```

The generic HTTP adapter keeps its existing JSON fields, Origin/Host, cookie, CSRF and rate-limit behavior; it does not automatically become the ChatVoice HTTP API. When retaining existing HTTP, the host still owns cookie/response mapping, Origin/CSRF checks, account creation and every business owner/policy decision. The `_chatlogin_session` entry in `resolve_row` is for server-side CSRF checks, not whole-row JSON serialization or sensitive-field logging.

Without FastAPI, install `ChatLogin[ui]` and call `LoginUI.render()`. That mode only renders templates; secure HTTP behavior remains the host's responsibility.

## Browser HTTP Contract {#browser-contract}

The default prefix is `/auth`; it can be explicitly configured as `/api/auth` or another fixed local prefix.

| Request | Purpose | Requirements |
| --- | --- | --- |
| `GET {prefix}/session` | Identity and CSRF; guests have `authenticated=false` | Trusted Host, no cache |
| `POST {prefix}/login` | Verify credentials, set cookie | JSON, exact Origin, size/rate bounds; a valid existing cookie also requires CSRF |
| `POST {prefix}/logout` | Revoke current session and delete cookie | Exact Origin and CSRF |
| `current_user` | Protected reads | 401 without a valid session |
| `csrf_user` | Cookie-authenticated writes | Identity, exact Origin and CSRF |
| `roles(...)` | Explicit role requirement | 401 if unauthenticated, 403 if role is insufficient |

Use browser fetch with `credentials: 'same-origin'`. Read CSRF from session JSON and send it as `X-CSRF-Token` for writes. Never store passwords, session cookies or CSRF in localStorage/sessionStorage or logs. Browsers generate Origin for same-origin POST requests; scripts do not need to forge that header.

`allow_native=True` explicitly permits a programmatic initial-login exception: a request without Origin or browser fetch-site semantics can send `X-ChatLogin-Client: native`. This header is not a credential; cookie writes still require canonical Origin and CSRF. The exception is disabled by default and does not enable cross-site CORS.

## Identity, Authorization and Storage

- Guest is unauthenticated state, not automatic account/session creation or migration of guest history.
- User/admin roles come only from a trusted backend. Use multiple explicit `PasswordBackend` entries or connect an existing database with `CallbackBackend`.
- `require_owner` applies equally to admins. Any admin access to other users' data must be a separate host policy.
- Random session tokens are delivered only through HttpOnly cookies; `SessionStore` receives digests. CSRF is a separate sensitive value, intentionally returned to same-origin clients but never logged.
- Expiry cleanup is triggered through `SessionManager.purge_expired()`. The manager calls the store with its own validated instance and clock. Hosts that maintain private context indexes should clean them at this boundary instead of duplicating TTL math or touching store internals.
- Bounded memory storage is for single-process tests/demos. SQLite is durable local storage; multi-host deployments need a shared `SessionStore`. Login limiting is a process-local backstop, not distributed abuse prevention.
- `SQLiteSessionStore` delegates to the public `PrivateSQLite` primitive. On POSIX, every real directory component is traversed no-follow: ancestors must be owned by root (including its user-namespace mapping) or the service UID and must not be writable by untrusted group/other users, except where sticky semantics demonstrably protect the trusted owner's entry. The final data directory must be service-UID-owned and exactly `0700`.
- The main database is opened at its real path with `mode=rw` after one exclusive secure initialization. Existing main databases and `-journal`/`-wal`/`-shm` files must be service-UID-owned, single-link, regular files with exact mode `0600`; existing paths are never chmodded. Safe sidecars SQLite creates inside the trusted parent are validated after connection/transaction activity and normalized to `0600` only when newly created. This does not rely on an fd alias and does not exclude a malicious same-UID process: same-UID processes and root are inside the local-filesystem trust boundary.
- POSIX platforms lacking the required dir-fd/no-follow primitives fail closed. Non-POSIX uses the isolated legacy compatibility path without POSIX no-follow/mode guarantees, so deployments must protect it with platform ACLs. The primitive is for trusted local filesystems, not network/shared filesystems.
- Configure a fixed trusted `origin`. Never infer it from arbitrary Host or forwarded headers. Proxy trust, TLS and process lifecycle belong to the host.

## Dependency Compatibility Gate

`ChatLogin[web]` now declares `starlette>=0.40,<2.0`. Compatibility tests cover:

- Current 0.x line: 338 passed / 6 browser-opt-in skipped.
- ChatShare target line: installed wheel with `FastAPI==0.133.1` + `Starlette==1.3.1`, 338 passed / 6 skipped.
- New 1.x probe: installed wheel with `FastAPI==0.141.1` + `Starlette==1.6.0`, 338 passed / 6 skipped.
- Clean `ChatLogin[ui]` wheel install without FastAPI/Starlette rendered `LoginUI` successfully.

The repository's `Web Compatibility` workflow still installs explicit 0.x and 1.3.x lines through the normal resolver for the `web` extra. The 1.x functional probes demonstrate runtime compatibility; run standard dependency resolution and the minimum-Python wheel gate before release.

## Runnable Demo

The packaged demo needs no checkout: install `ChatLogin[demo]` and run `chatlogin serve`. It uses an explicitly labelled public synthetic identity; see [Demo](demo.md).

The following separate source example demonstrates host-supplied credentials; it is not required by `serve`.

From the source distribution or repository root. The demo has no default password and uses synthetic accounts rather than production data:

```bash
python -m pip install -e ".[web,demo]"
read -s CHATLOGIN_DEMO_PASSWORD
export CHATLOGIN_DEMO_PASSWORD
python -m uvicorn examples.demo_fastapi:create_app --factory --host 127.0.0.1 --port 10081
```

Use a temporary password of at least 12 characters. The demo username is `demo`. Open `http://127.0.0.1:10081/api/auth/`, sign in, return to the host homepage, and sign out. `/private` is a protected read endpoint. This is a local test address, not a deployed public website.

## Customization Responsibility

Default templates autoescape text and serve packaged static assets. Custom renderers are trusted host code and must handle their own HTML safety. Styling must not weaken cookies, CSRF or resource ownership checks.
