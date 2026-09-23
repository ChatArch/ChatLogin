# Integrate Your Own Project

<div class="grid cards" markdown>

- **New FastAPI host**: copy the complete application below and perform a real login.
- **Existing account database**: retain accounts/password material and use a [sync or async callback](integration.md#backends).
- **Existing frontend**: mount `ui=None` JSON routes and follow the [browser contract](integration.md#browser-contract).
- **Choose a visual style**: use the [demo](demo.md) template playground and copy its `LoginUI(...)` configuration.

</div>

## 1. Install and Save the Application

```bash
python -m pip install "ChatLogin[web]" uvicorn
```

Save this complete code as `app.py`. The account is `operator`; you must explicitly provide its password. It does not reuse the public demo identity or provide a default production password.

```python
"""Minimal host app; provide an explicit password through the environment."""
import os
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI
import uvicorn
from chatlogin import MemorySessionStore, PasswordBackend, Principal, SessionManager, hash_password
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

origin = os.environ.get("MY_SITE_ORIGIN", "http://127.0.0.1:8000")
password = os.environ["MY_SITE_LOGIN_PASSWORD"]
backend = PasswordBackend({
    "operator": (Principal("operator", "Operator"), hash_password(password)),
})
app = FastAPI()
auth = FastAPIAuth(
    backend,
    SessionManager(MemorySessionStore(max_sessions=256), instance="my-site", ttl=3600),
    origin=origin,
    ui=LoginUI(),
    cookie=CookieSettings(secure=urlsplit(origin).scheme == "https"),
)
app.include_router(auth.router)

@app.get("/")
def home():
    return {"login": "/auth/?next=/private"}

@app.get("/private")
def private(user=Depends(auth.current_user)):
    return user.as_dict()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False)
```

## 2. Set an Explicit Password and Run

In Bash/Zsh, enter the following commands and a test password of at least 12 characters. Input is hidden and does not enter command-line arguments.

```bash
read -rs MY_SITE_LOGIN_PASSWORD
export MY_SITE_LOGIN_PASSWORD
python app.py
```

Open <http://127.0.0.1:8000/auth/?next=/private> and sign in as `operator`. `/private` then returns the server-trusted principal; anonymous direct access returns 401.

The sample uses single-process memory sessions that disappear on restart. Production hosts should select durable storage, a fixed HTTPS origin, and explicit business-data authorization. Never reuse the public demo identity in a real application.

## 3. Select the Frontend Independently

| Preserve | Configuration | Host responsibility |
| --- | --- | --- |
| Default UI | `ui=LoginUI(palette="forest", layout="split")` | Account source and business routes |
| Host branding/templates | `LoginUI(template_dirs=("templates",), template_name="host/login.html")` | Trusted templates and static assets |
| Existing HTML/JS | `ui=None` | Form, error feedback and navigation |
| Standard-library HTTP host | `LoginUI.render(context)` | Cookies, Origin, CSRF and HTTP routes |

Template directories must exist and are trusted host code. Do not edit site-packages. Template selection and credential backend choice are independent. Optional `script_url` accepts a canonical same-origin local path; no host script is loaded by default.

## 4. Headless Request Sequence

1. `GET /auth/session` returns HTTP 200 with `authenticated=false` for an anonymous browser.
2. `POST /auth/login` sends JSON `username`, `password`, and `next`. The browser supplies Origin. With an existing valid session, bootstrap current CSRF first and send `X-CSRF-Token`.
3. Use `credentials: 'same-origin'` for protected requests. Cookies are sent automatically; never read the token manually.
4. Send current CSRF for writes. Refresh session state before `POST /auth/logout`.
5. Clear private UI after logout; protected endpoints return 401 again.

The installed `chatlogin.demo_site/assets/demo.js` contains the runnable headless example. Its synthetic business data does not imply your own backend is connected.

## Next Steps

- [Integration and Security](integration.md): backend selection, exact ChatVoice schema and HTTP/role/owner boundaries.
- [Python Interface Tree](interface-tree.md): importable classes and methods.
- [Demo](demo.md): run the isolated site and preview configuration.
