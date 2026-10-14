# New-service onboarding: one account HTTP contract

ChatLogin 0.2.1 mounts an account plugin **inside each service**. One `create_managed_auth` provides login, sessions, profile and user management. Choose a gear menu, ordinary links or a host frontend without copying authentication. This is not shared-cookie SSO, a central identity service or generic CRUD for arbitrary external account providers.

## An end-to-end new service

```bash
python -m pip install "ChatLogin[web]==0.2.1" uvicorn
chatlogin users bootstrap operator --instance my-service --password-env MY_SERVICE_BOOTSTRAP_PASSWORD
```

Provide the bootstrap variable through a protected process environment first. The CLI receives its name, never a password value. No production account is created automatically. Save the [complete factory](https://github.com/ChatArch/ChatLogin/blob/main/examples/managed_service.py) as `auth_app.py`, then create `app.py`:

```python
import os
from auth_app import create_app
from chatlogin.account_ui import AccountMenuUI

app = create_app(
    instance="my-service",
    origin=os.environ["MY_SERVICE_ORIGIN"],
    prefix="/auth",  # /admin is another deployment prefix, not a permission grant
    menu_ui=AccountMenuUI(mode="gear", language="en"),
    allow_insecure_loopback=os.environ.get("MY_SERVICE_ALLOW_LOOPBACK") == "1",
)
```

Production uses the actual fixed HTTPS browser origin; the host owns TLS and reverse proxying:

```bash
MY_SERVICE_ORIGIN=https://service.example.com python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

For explicit local development only:

```bash
MY_SERVICE_ORIGIN=http://127.0.0.1:8765 MY_SERVICE_ALLOW_LOOPBACK=1 python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

Open the homepage → Account settings → Login. Owners/admins can open management; members have their own profile. `/private` uses `auth.current_user`; `/operator` requires explicit admin/owner roles. Business-resource ownership still belongs to the host: roles do not bypass `require_owner` or ACLs.

The factory closes a store it creates during ASGI shutdown. An injected service is caller-owned and must be closed by the caller, so one host cannot destroy another host's shared in-process service. Synthetic in-memory users are only explicit test fixtures, not production defaults or an automatic migration.

## A discoverable API root

`GET /auth/api` returns `version` (installed package), `schema_version=1` (discovery format), actual `{method, path}` `operations`, available `pages` and `login`/`managed_users`/`profile` `capabilities`. With `/admin`, the root is `/admin/api`. URLs include trusted ASGI mount metadata, not forwarded-prefix headers.

Host checking and `no-store` apply. Discovery reveals no account directory, Cookie, CSRF, credentials or state paths. It advertises provided capabilities, not actor permissions. Fixed/callback backends do not claim managed-user administration; headless mode advertises no pages. This operation directory is not a complete request/response schema or an OAuth endpoint.

| Method and relative path | JSON / result | Authorization |
| --- | --- | --- |
| `GET /api` | Discovery | Trusted Host, anonymous allowed |
| `GET /session` | authenticated, user, csrf_token | Trusted Host; anonymous gets 200 |
| `POST /login` | username, password, optional next | Same-origin; existing session needs CSRF |
| `POST /logout` | Revoke session | Current session, Origin, CSRF |
| `GET /api/users?offset=0&limit=100` | Safe metadata list, limit≤100 | Owner/admin within policy scope |
| `POST /api/users` | username, password, optional display_name/role; 201 | Owner/admin; only owner grants admin |
| `GET /api/users/{user_id}` | Safe metadata | Object-scoped owner/admin |
| `PATCH /api/users/{user_id}` | Allowed display_name/role/enabled combination | Object policy, Origin, CSRF |
| `DELETE /api/users/{user_id}` | deleted | Object policy, Origin, CSRF; never delete owner |
| `POST /api/users/{user_id}/password` | new_password | Object policy, Origin, CSRF |
| `GET /api/profile` | Own profile | Current user |
| `PATCH /api/profile` | display_name | Self, Origin, CSRF |
| `POST /api/profile/password` | current_password, new_password | Self, Origin, CSRF; invalidate old sessions |
| `POST /api/owner/transfer` | target_user_id, current_password, confirm_username | Owner reauthentication, Origin, CSRF, atomic handoff |

Use browser `credentials: 'same-origin'`, read current CSRF from `/session` and send `X-CSRF-Token` for writes. Never persist credentials, Cookie or CSRF in browser storage, URLs or logs. Common errors: 400 invalid request/Host; 401 unauthenticated; 403 policy/Origin/CSRF; 404 missing object; 409 conflict; 413 oversized body; 429 rate limit; 503 controlled capacity/service failure. The operation catalog supplements this contract and host OpenAPI; it does not replace request/response schemas.

## Gear, links and DIY

```python
from chatlogin.account_ui import AccountMenuUI

menu = await auth.render_account_menu(request)  # Chinese-first native details
menu = await auth.render_account_menu(request, ui=AccountMenuUI(mode="links", language="en"))
menu = await auth.render_account_menu(
    request, ui=AccountMenuUI(template_dirs=["templates"], template_name="account/menu.html")
)
navigation = await auth.navigation_from_request(request)  # host-owned rendering
```

Host HTML containing current identity must also set `Cache-Control: no-store`; never share-cache an account menu. Navigation resolves the actual current session. Anonymous visitors see login; members see profile; admins/owners also see management. Changes invalidate stale sessions. The native vertical gear popover needs no JavaScript initialization, has scoped CSS and inherits host typography/theme. Default rendering escapes identity/labels and validates local links; trusted custom renderers own HTML safety. Sign-out remains the existing CSRF-protected POST, not a GET link.

`pages=False` retains JSON APIs without packaged HTML/assets and produces no fake empty settings control. Host frontends use the same HTTP contract. `LoginUI`, `UserAdminUI` and `UserProfileUI` remain separately replaceable; never patch site-packages. Existing account providers retain their own lifecycle unless an explicit managed adapter exists. A unified HTTP contract is not a shared account database or cross-site SSO. See [Managed Users](managed-users.en.md) and [Integration and Security](integration.en.md).
