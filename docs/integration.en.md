# Integration and Security Boundaries

## Choose an Integration Level

| Requirement | Entry point | Host responsibilities |
| --- | --- | --- |
| Ready-to-use login page | `FastAPIAuth(..., ui=LoginUI(...))` | User source, business routes, deployment and TLS |
| Custom brand or layout | `LoginUI(template_dirs=..., template_name=...)` or `renderer` | Custom HTML/CSS and renderer safety |
| Existing HTML/JS frontend | `FastAPIAuth(..., ui=None)` | Existing page, frontend state, all business data |
| Existing HTTP/database contract | `CallbackBackend`, `SessionManager`, host `SessionStore` | Stable account IDs, password data, session mapping and response compatibility |

Headless does not require another auth microservice. Mount JSON routes in the existing FastAPI process, or call the core Python API while keeping existing HTTP handlers and response fields. Python packages can carry HTML/CSS/JS; host templates take priority over package templates, without editing site-packages.

## Browser HTTP Contract

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
- Bounded memory storage is for single-process tests/demos. SQLite is durable local storage; multi-host deployments need a shared `SessionStore`. Login limiting is a process-local backstop, not distributed abuse prevention.
- Configure a fixed trusted `origin`. Never infer it from arbitrary Host or forwarded headers. Proxy trust, TLS and process lifecycle belong to the host.

## Runnable Demo

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
