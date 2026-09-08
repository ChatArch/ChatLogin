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
├── PasswordBackend(accounts)         # fixed single account or multiple accounts
└── CallbackBackend(authenticate)     # host user database / existing hash verification

chatlogin
├── SessionStore                      # Protocol
├── MemorySessionStore(max_sessions)  # demo/test only
├── SQLiteSessionStore(database)
├── SQLiteSessionStore.for_instance(instance, home=None)
├── Session / IssuedSession
└── SessionManager(store, instance, ttl)
    ├── issue(principal, previous_token=None)
    ├── resolve(token)
    ├── revoke(token)
    └── digest(token)

chatlogin
├── require_csrf(session, submitted)
├── safe_next(value, default="/")
└── LoginRateLimiter(limit, window, max_keys)
```

## FastAPI Adapter

Available with `ChatLogin[web]`:

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

```text
chatlogin.ui
└── LoginUI(
      title,
      subtitle,
      palette="indigo" | "forest" | "amber",
      layout="card" | "split",
      template_dirs=(),
      template_name="chatlogin/login.html",
      stylesheet_url=None,
      renderer=None,
    )
```

Host templates in `template_dirs` take precedence over packaged templates. A host template can extend `chatlogin/login.html` and override one block, replace the whole page, or a callable renderer can return HTML directly.

## Minimal Host Backend

```python
from chatlogin import CallbackBackend, Principal

def authenticate(username: str, password: str) -> Principal | None:
    row = my_user_database.find(username)
    if row and verify_pbkdf2(password, row.salt, row.digest, iterations=row.iterations):
        return Principal(row.id, row.display_name, Role(row.role))
    return None

backend = CallbackBackend(authenticate)
```

The host continues to own its account table, password material, resource owners, and policies. ChatLogin creates no default production account and never treats `admin` as permission to read every resource.

## Runtime Paths

```python
from chatlogin import SQLiteSessionStore, state_paths

paths = state_paths("my-site")
store = SQLiteSessionStore.for_instance("my-site")
```

The default path is `<ChatArch home>/chatlogin/instances/<instance>/sessions.sqlite3`. Importing the package or calculating paths creates nothing. Store initialization creates only its own private directory and a `0600` database; shared parent modes are unchanged.
