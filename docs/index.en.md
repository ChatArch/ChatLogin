# ChatLogin Documentation

ChatLogin makes the backend security contract for website login reusable in Python while leaving presentation under host control. Use the packaged page, override templates/CSS, or keep an existing HTML/vanilla-JS frontend and use the headless JSON API.

Site entry: <https://arch.gh.wzhecnu.cn/ChatLogin/en/>

## Choose Documentation by Scenario

<div class="grid cards" markdown>

- **FastAPI integration**

    Install the `web` extra and mount configurable auth routes, dependencies, and an optional page.

    [Open Interface Tree](interface-tree.md)

- **Keep an existing visual style**

    Choose packaged UI, host template overrides, or a fully headless host-owned frontend.

    [Open Capability Map](capability-map.md)

- **Review CLI and package boundaries**

    The CLI exposes version and standard command trees; authentication is first an importable Python API.

    [Open CLI Tree](cli-tree.md)

</div>

## Install

```bash
python -m pip install "ChatLogin[web]"
```

The smallest FastAPI integration uses either synthetic accounts or a host-provided callback. There is no built-in production password.

```python
from fastapi import Depends, FastAPI
import os
from chatlogin import PasswordBackend, MemorySessionStore, Principal, SessionManager, hash_password
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

backend = PasswordBackend({
    "demo": (Principal("usr_1", "Demo user"), hash_password(os.environ["EXAMPLE_LOGIN_PASSWORD"]))
})
auth = FastAPIAuth(
    backend,
    SessionManager(MemorySessionStore(), instance="my-site"),
    origin="https://www.example.com",
    prefix="/api/auth",
    ui=LoginUI(title="My site"),
    cookie=CookieSettings(name="my_site_session"),
)
app = FastAPI()
app.include_router(auth.router)

@app.get("/private")
def private(principal=Depends(auth.current_user)):
    return principal.as_dict()
```

See `examples/demo_fastapi.py` for a runnable synthetic-account demo.

## Three Frontend Levels

| Level | Best for | Security boundary |
| --- | --- | --- |
| Default UI | New sites | Packaged HTML/CSS/JS, palettes, and layouts with the same opaque-cookie backend |
| Host override | Brand or partial/full page customization | Jinja choice loading, block inheritance, and local custom CSS without editing site-packages |
| Headless | Existing static HTML/vanilla-JS apps such as ChatVoice | No default page or assets; only `/login`, `/session`, and `/logout` JSON contracts |

Themes affect presentation only. They cannot weaken CSRF, cookies, roles, or owner checks. Default resources use scoped `.chatlogin` classes and CSS variables rather than global resets.

## Secure Defaults

- Server-trusted identities are `guest`, `user`, and `admin`; login payloads cannot escalate role.
- Credential verification is injectable: fixed account, multiple accounts, or a host callback. Existing PBKDF2 material can be verified without forced migration.
- Session tokens are random; only SHA-256 digests are stored. Expiry, rotation, revocation, and instance isolation are supported.
- Cookies default to `HttpOnly`, `Secure`, and `SameSite=Lax`; cookie-authenticated writes require same-site Origin and CSRF.
- `next` accepts only local absolute paths; login bodies are bounded and rate limited.
- Roles do not bypass resource ownership, including admin.
