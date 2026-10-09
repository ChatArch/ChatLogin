# Python Interface Tree

## Core Layer

```text
chatlogin
├── __version__
├── Principal / Role
│   ├── Principal.guest()
│   └── principal.authenticated
├── require_user(principal)
├── require_role(principal, *roles)
└── require_owner(principal, owner_id)

chatlogin
├── PasswordHash
├── hash_password(password)
├── verify_pbkdf2(password, salt, digest, iterations=310000)
├── CredentialBackend                 # Protocol: authenticate(username, password)
├── AsyncCredentialBackend            # Protocol: async authenticate(username, password)
├── PasswordBackend(accounts)         # fixed single account or multiple accounts
├── CallbackBackend(authenticate)     # host user database / existing hash verification
└── AsyncCallbackBackend(authenticate) # async host database / upstream verification

chatlogin
├── SessionStore                      # Protocol
├── MemorySessionStore(max_sessions)  # demo/test only
├── PrivateSQLite(database, timeout=5)
│   └── connect(immediate=False)
├── SQLiteSessionStore(database)
├── SQLiteSessionStore.for_instance(instance, home=None)
├── Session / IssuedSession
└── SessionManager(store, instance, ttl)
    ├── issue(principal, previous_token=None)
    ├── resolve(token)
    ├── purge_expired()
    ├── revoke(token)
    └── digest(token)

chatlogin
├── require_csrf(session, submitted)
├── safe_next(value, default="/")
└── LoginRateLimiter(limit, window, max_keys)
```

## Built-in Optional ChatVoice Backend

```text
chatlogin.backends.chatvoice
├── ChatVoiceAuth(connect, lock, clock, *, ttl, max_sessions=10000)
│   ├── login(account, password) -> IssuedSession | None
│   ├── resolve_row(token) -> dict | None
│   ├── check_csrf(auth, submitted)
│   ├── logout(token)
│   └── store / backend / manager
└── ChatVoiceSessionStore(connect, lock, clock, *, max_sessions=10000)
    ├── put(instance, digest, session, *, previous_digest=None)
    ├── get(instance, digest) / read_row(instance, digest)
    ├── session_from_row(row)
    ├── delete(instance, digest)
    └── purge_expired(instance, now)
```

Available in the core package, also exported from `chatlogin.backends`. Fixed ChatVoice schema / `chatvoice` namespace, USER identities only; no table creation, migration, account management, HTTP or owner policy. See [Integration](integration.en.md) for all three UI modes.

## FastAPI Adapter

Available with `ChatLogin[web]`. `FastAPIAuth` accepts a sync `CredentialBackend` or an async `AsyncCredentialBackend`; sync calls run in the threadpool and async calls are awaited.

```text
chatlogin.fastapi
├── FastAPIAuth
│   ├── router
│   ├── current_user(request) -> Principal
│   ├── csrf_user(request) -> Principal
│   ├── roles(*roles) -> FastAPI dependency
│   └── cookie / sessions / ui
├── CookieSettings(name, path, max_age, secure, same_site, http_only)
├── GET  {prefix}/session
├── POST {prefix}/login
└── POST {prefix}/logout
```

When `LoginUI` is provided, these routes are also registered:

```text
GET {prefix}/                  # packaged or host-overridden login page
GET {prefix}/assets/login.css
GET {prefix}/assets/login.js
```

Without `LoginUI`, no page or asset route is registered. This is the headless mode for hosts that keep their own HTML and JavaScript.

## UI Layer

Install `ChatLogin[ui]` when only UI rendering is needed; it installs Jinja2 without FastAPI. `ChatLogin[web]` includes the UI dependency plus FastAPI/Starlette.

```text
chatlogin.ui
└── LoginUI(
      title,
      subtitle,
      palette="indigo" | "forest" | "amber",
      layout="card" | "split",
      appearance="system" | "light" | "dark",
      guest_url=None,
      guest_label="Continue as guest",  # explicit localization override
      template_dirs=(),
      template_name="chatlogin/login.html",
      stylesheet_url=None,
      renderer=None,
      script_url=None,
    )
```

Host templates in `template_dirs` take precedence over packaged templates. A host template can extend `chatlogin/login.html` and override one block, replace the whole page, or a callable renderer can return HTML directly.

## Minimal Host Backend

```python
from chatlogin import CallbackBackend, Principal, Role, verify_pbkdf2

def authenticate(username: str, password: str) -> Principal | None:
    row = my_user_database.find(username)
    if row and verify_pbkdf2(password, row.salt, row.digest, iterations=row.iterations):
        return Principal(row.id, row.display_name, Role(row.role))
    return None

backend = CallbackBackend(authenticate)
```

Use `AsyncCallbackBackend` for async upstreams:

```python
from chatlogin import AsyncCallbackBackend, Principal

async def authenticate(username: str, password: str) -> Principal | None:
    row = await upstream.verify(username, password)
    return Principal(row.id, row.display_name) if row else None

backend = AsyncCallbackBackend(authenticate)
```

Both sync and async callbacks validate username/password UTF-8 byte limits before calling host code. Invalid input is not passed to the callback; host code must return an authenticated `Principal` or `None`, and guest/other objects fail closed.

The host continues to own its account table, password material, resource owners, and policies. ChatLogin creates no default production account and never treats `admin` as permission to read every resource.

## Runtime Paths

```python
from chatlogin import PrivateSQLite, SQLiteSessionStore, state_paths

paths = state_paths("my-site")
store = SQLiteSessionStore.for_instance("my-site")
private = PrivateSQLite(paths.directory / "leaf-package.sqlite3")
```

The default session path is `<ChatArch home>/chatlogin/instances/<instance>/sessions.sqlite3`. Importing the package or calculating paths creates nothing; initializing `PrivateSQLite` or the store securely creates missing private directories and the main database. Leaf packages can reuse the boundary with `with private.connect() as connection:`. A normal context exit commits, an exception rolls back, and `immediate=True` runs `BEGIN IMMEDIATE` before yielding the connection.

The POSIX implementation traverses every ancestor no-follow and validates ownership/write access; the final data directory must be service-UID-owned and exactly `0700`. It opens the main database at its real file URI with `mode=rw`. Existing main databases and sidecars must be service-UID-owned, single-link, regular files with exact mode `0600` and are never chmodded; only safe sidecars newly created by SQLite inside the trusted parent may be normalized to `0600`. The boundary does not rely on an fd alias and does not exclude same-UID processes; same-UID processes and root are trusted here.

POSIX systems without the required dir-fd/no-follow primitives fail closed. Non-POSIX systems retain the isolated legacy path without POSIX mode guarantees, so the host must protect the directory with platform ACLs. This API is for a trusted local filesystem, not a network/shared filesystem.

When a host needs to clean a private context index, call `SessionManager.purge_expired()`. The manager delegates to the store with its validated instance and clock; do not duplicate TTL calculations or access store internals.
## Packaged Demo Application

With `ChatLogin[demo]`, `chatlogin.demo.create_demo_app(origin=...)` returns the isolated demo application; `chatlogin serve` is its thin CLI. It exercises real backends/UI without becoming a production identity center. See [Quick Integration](quickstart.md) and [Demo](demo.md).

## Demo-Host Isolation Endpoints

These routes belong only to the development demo application, not a production account-management API.

| Request | Contract |
| --- | --- |
| `GET /api/demo/accounts` | Returns only explicit public synthetic A/B credentials; never reads a host user database |
| `GET /api/demo/{mode}/records` | Lists only the authenticated user's samples |
| `GET /api/demo/{mode}/records/{id}` | Requires the current user to be the owner |
| `POST /api/demo/{mode}/records/{id}/touch` | Same origin, current-session CSRF, owner; accepts no request body |

See the [multi-user boundary](demo.en.md#user-isolation).
