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
├── ChatVoiceAuth(connect, lock, clock, *, ttl)
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
      guest_label="以访客身份继续",
      template_dirs=(),
      template_name="chatlogin/login.html",
      stylesheet_url=None,
      renderer=None,
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
from chatlogin import SQLiteSessionStore, state_paths

paths = state_paths("my-site")
store = SQLiteSessionStore.for_instance("my-site")
```

The default path is `<ChatArch home>/chatlogin/instances/<instance>/sessions.sqlite3`. Importing the package or calculating paths creates nothing. Store initialization creates only its own private directory and a `0600` database; shared parent modes are unchanged.

When a host needs to clean a private context index, call `SessionManager.purge_expired()`. The manager delegates to the store with its validated instance and clock; do not duplicate TTL calculations or access store internals.
