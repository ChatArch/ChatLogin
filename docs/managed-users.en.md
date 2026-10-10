# Managed Users

This page describes the managed-users preset planned for `0.2.0`. New adopters should explicitly require `ChatLogin>=0.2.0,<0.3.0`. Existing fixed-account, callback, and ChatVoice-compatible integrations do not need to change. A legacy ChatVoice consumer's `<0.2` dependency remains unaffected unless it deliberately adopts managed users.

## Choose the Right Entry Point

| Need | Entry point | Account and business boundary |
| --- | --- | --- |
| An application-owned owner/admin/user directory, login page, profile, and user management | `ManagedUsers` + `create_managed_auth` | ChatLogin manages accounts/sessions for that instance; the host still authorizes business data |
| Accounts already belong to a host or upstream service | `CallbackBackend` / `AsyncCallbackBackend` | The host keeps accounts, password material, and lifecycle |
| A few explicit fixed accounts | `PasswordBackend` | The host configures account entries |
| An existing ChatVoice schema | `ChatVoiceAuth` | The compatibility layer does not create or migrate account tables |

Managed users are an opt-in preset. They do not migrate an old user database, convert legacy backends, or claim SSO, OAuth, or MFA. They also do not make `owner` or `admin` a bypass for host business data: routes still need host-owned checks such as `require_owner(user, record.owner_id)`.


## Integrate as a Plugin {#plugin}

ChatLogin does not own the business server or require a separate identity microservice. Install it, select an account backend, and mount the plugin. Login, identity, sessions, CSRF, roles, and optional pages reuse one component. The host still authorizes business records, downloads, jobs, and data ownership.

| Integration | Setting | Reused mechanisms |
| --- | --- | --- |
| Packaged pages | `create_managed_auth(..., pages=True)` | Login, account administration, profile templates and all protected APIs |
| Existing frontend | `create_managed_auth(..., pages=False)` | Session/login/logout and account APIs only; no packaged HTML or asset routes |
| Existing account database | Existing backend + `FastAPIAuth`/core APIs | Preserve schema and password material while reusing sessions and checks; no automatic account-lifecycle takeover |

```python
auth = create_managed_auth(
    instance="mytool",
    origin="https://app.example.com",
    pages=False,  # Keep the application's own login and management frontend.
)
app.include_router(auth.router)
```

Consumers need not copy hashing, sessions, CSRF, or authorization implementations. Existing callback/ChatVoice/Dufs adapter accounts are not automatically imported into the managed directory. Other HTTP hosts can compose `ManagedUsers`, `SessionManager`, and security checks directly. Non-Python frontends call the host-mounted same-origin APIs; this is not an OAuth/cross-site SSO SDK.

## Minimal Mount

An explicit operator creates the first owner before the web application starts. The password value stays in the environment; the command receives the environment-variable **name**, never a password argument:

```bash
# Supply APP_BOOTSTRAP_CREDENTIAL through a protected process environment; do not put its value in shell history.
chatlogin users bootstrap operator \
  --instance mytool \
  --password-env APP_BOOTSTRAP_CREDENTIAL \
  --display-name "Operator"
```

Bootstrap is allowed only for an empty account instance. A repeat bootstrap, unsafe state path, or invalid input fails nonzero. There is no `--force`, chmod repair, or automatic confirmation. Use `--home` only for an explicit ChatArch home; `--json` emits only safe `UserRecord` fields, never credentials, hashes, cookies, or CSRF.

The smallest FastAPI mount is:

```python
import os

from fastapi import Depends, FastAPI
from chatlogin.managed_web import create_managed_auth

app = FastAPI()
auth = create_managed_auth(
    instance="mytool",
    origin=os.environ["MYTOOL_ORIGIN"],
)
app.include_router(auth.router)

@app.get("/private")
async def private(user=Depends(auth.current_user)):
    return {"user_id": user.user_id}
```

When an application needs an explicit service object, such as for a custom lifecycle or test, create it and pass the same object:

```python
from chatlogin.managed import ManagedUsers
from chatlogin.managed_web import create_managed_auth

users = ManagedUsers.for_instance("mytool")
auth = create_managed_auth(instance="mytool", origin="https://app.example", users=users)
```

`ManagedUsers.for_instance(instance, home=None, ...)` uses durable storage controlled by that account instance. `ManagedUsers.in_memory(instance, ttl=300, max_users=..., max_sessions=...)` is only for explicit tests or demos; it reads neither profile nor home and its lifetime must be closed at app shutdown.

## Roles and Operations

| Operation | owner | admin | user |
| --- | --- | --- | --- |
| Sign in; view/update own profile; change own password | Yes | Yes | Yes |
| User-management page and list | All safe metadata | Ordinary users and self | No |
| Create an ordinary user | Yes | Yes | No |
| Create or grant admin | Yes | No | No |
| Disable, delete, or reset an ordinary user's password | Yes | Yes | No |
| Manage another admin | Yes | No | No |
| Directly disable, delete, or demote owner | No | No | No |
| Transfer owner | Explicit target-username confirmation, current-password verification, atomic transfer | No | No |

Each account instance has one enabled owner. Transfer invalidates both the former owner's and target user's sessions; role, enabled-state, deletion, and password changes invalidate affected old sessions too. Do not mix application-record ownership into this table: `require_owner` remains a host-owned business rule.

## Web, Templates, and Headless

`create_managed_auth(...)` returns `ManagedAuth` with `.router`, `.users`, `.current_user`, `.csrf_user`, `.admin_user`, and `.cookie`. Its default prefix is `/auth`:

| Path | Purpose |
| --- | --- |
| `/auth/` | Login page |
| `/auth/users` | User-management page |
| `/auth/profile` | Current-user profile page |
| `/auth/api/users` | User list, creation, and management API |
| `/auth/api/profile` | Current-user profile/password API |
| `/auth/api/owner/transfer` | Owner-transfer API |
| `/auth/session`, `/auth/login`, `/auth/logout`, `/auth/assets` | Inherited session, login, logout, and static-asset routes |

The default `LoginUI`, `UserAdminUI`, and `UserProfileUI` share theme, palette, and appearance conventions. A trusted host can override templates or renderers; a headless integration retains host pages and calls the protected APIs. Whatever page is used, the backend keeps Host/Origin, session, CSRF, and role enforcement.

The account/session **directory and instance namespace** comes from `instance`. `origin` configures browser Host/Origin checks and cookie safety; a URL, proxy header, or request body never selects an account database. Under a subpath mount, generated UI and asset URLs stay within the trusted mount/root path.

## Standalone Synthetic Demo

With the `demo` extra installed, start the dedicated real-preset demo:

```bash
chatlogin serve --managed-demo
```

It builds three clearly public synthetic owner, admin, and user accounts with `ManagedUsers.in_memory(...)` and real `bootstrap_owner`, `authenticate`, and `create_user` calls. It reads no user home/profile, production account database, or production sessions. `/health` returns only the version, `managed-demo` mode, and synthetic flag; the public fixtures API returns only deliberately public synthetic values. Default `chatlogin serve` remains the existing four-backend demo unchanged.

## Migration and Security Boundary

- There is no automatic migration of an old user database and no deletion or rewriting of host business data.
- There is no SSO, OAuth, MFA, email, SMS, or QR-code authentication claim.
- Fixed-account, callback, and ChatVoice adapters keep account-management responsibility in the host; they do not gain a managed-user administration page.
- Production hosts still own fixed HTTPS origin, TLS, reverse proxy, process lifecycle, and business authorization.
- Point `--password-env` only at a controlled environment variable; never log its value, a cookie, CSRF, password hash, or session token.
