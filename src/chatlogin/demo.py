"""Self-contained, synthetic product demonstration for ``chatlogin serve``.

This module belongs to the optional ``demo`` extra.  It never consults ChatEnv,
user homes, production providers, forwarded headers, or persistent databases.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from html import escape
from importlib import resources
import hashlib
import hmac
import sqlite3
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import (
    AsyncCallbackBackend,
    CallbackBackend,
    MemorySessionStore,
    PasswordBackend,
    Principal,
    SessionManager,
    __version__,
    hash_password,
)
from .backends import ChatVoiceAuth
from .fastapi import CookieSettings, FastAPIAuth
from .ui import APPEARANCES, LAYOUTS, PALETTES, LoginUI

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "chatlogin-demo"
DEMO_TTL_SECONDS = 300
DEMO_MAX_SESSIONS = 16

_ASSETS = {
    "demo.css": "text/css; charset=utf-8",
    "demo-login.css": "text/css; charset=utf-8",
    "demo.js": "application/javascript; charset=utf-8",
    "demo-login.js": "application/javascript; charset=utf-8",
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
)


@dataclass(frozen=True)
class _Mode:
    key: str
    backend_label: str
    ui_label: str
    auth: FastAPIAuth


class _FixedHostMiddleware:
    """Small pure-ASGI exact Host gate; forwarded headers are never consulted."""

    def __init__(self, app, *, authority: str):
        self.app = app
        self.authority = authority.encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            hosts = [value.lower() for name, value in scope.get("headers", ()) if name.lower() == b"host"]
            if hosts != [self.authority]:
                await _json({"detail": "Invalid Host header"}, 400)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _resource(kind: str, name: str) -> str:
    return (resources.files("chatlogin.demo_site") / kind / name).read_text(encoding="utf-8")


def _versioned_assets(markup: str) -> str:
    for name in _ASSETS:
        for quote in ('"', "'"):
            markup = markup.replace(f"{quote}/assets/{name}{quote}", f"{quote}/assets/{name}?v={__version__}{quote}")
    return markup.replace("{{VERSION}}", escape(__version__))


def _page(html: str, *, frame: bool = False) -> HTMLResponse:
    response = HTMLResponse(_versioned_assets(html))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Content-Security-Policy"] = _CSP if frame else _CSP.replace("frame-ancestors 'self'", "frame-ancestors 'none'")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _json(payload: dict, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(payload, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _replace(template: str, **values: object) -> str:
    for name, value in values.items():
        template = template.replace("{{" + name + "}}", escape(str(value)))
    return template


def _host_override(context: dict) -> str:
    """Trusted local renderer used to demonstrate a genuine host-owned page."""
    return _versioned_assets(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(str(context['title']))}</title>
<link rel="stylesheet" href="{escape(str(context['assets_path']))}/login.css">
<link rel="stylesheet" href="/assets/demo.css">
<link rel="stylesheet" href="/assets/demo-login.css">
<script defer src="{escape(str(context['assets_path']))}/login.js"></script>
<script defer src="/assets/demo-login.js"></script></head>
<body class="host-override"><main class="chatlogin host-login" data-palette="forest" data-layout="card"
 data-appearance="light" data-login-url="{escape(str(context['login_url']))}"
 data-session-url="{escape(str(context['session_url']))}" data-next="{escape(str(context['next']))}">
<a class="back-link" href="/">← ChatLogin</a><section class="host-login__card">
<p class="demo-kicker">宿主自定义界面 · 同步回调</p><h1>{escape(str(context['title']))}</h1>
<p>{escape(str(context['subtitle']))}</p><form class="chatlogin__form">
<label><span>账号</span><input name="username" autocomplete="username" required></label>
<label><span>密码</span><input name="password" type="password" autocomplete="current-password" required></label>
<button type="submit">登录</button><p class="chatlogin__status" role="status"></p>
</form></section></main></body></html>""")


def _memory_auth(backend, *, origin: str, mode: str, ui: LoginUI | None) -> FastAPIAuth:
    return FastAPIAuth(
        backend,
        SessionManager(MemorySessionStore(max_sessions=DEMO_MAX_SESSIONS), instance=f"serve-{mode}", ttl=DEMO_TTL_SECONDS),
        origin=origin,
        prefix=f"/demo/{mode}",
        ui=ui,
        cookie=CookieSettings(
            name=f"chatlogin_demo_{mode}", path="/", max_age=DEMO_TTL_SECONDS,
            secure=urlsplit(origin).scheme == "https", same_site="strict",
        ),
    )


def _chatvoice_fixture():
    """Create a process-local shared-memory copy of the exact legacy schema."""
    uri = f"file:chatlogin-demo-{uuid4().hex}?mode=memory&cache=shared"

    def connect():
        db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    keeper = connect()
    keeper.executescript("""
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
            password_salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE auth_sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL,
            created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES accounts(id) ON DELETE CASCADE
        );
    """)
    salt = b"ChatLoginDemoSalt"
    digest = hashlib.pbkdf2_hmac("sha256", DEMO_PASSWORD.encode(), salt, 310_000)
    keeper.execute(
        "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)",
        ("demo-chatvoice", DEMO_USERNAME, "ChatVoice 合成用户", salt, digest, datetime.now(timezone.utc).isoformat()),
    )
    keeper.commit()
    return keeper, connect


def create_demo_app(*, origin: str) -> FastAPI:
    """Build the isolated demo app for one explicit, trusted browser origin."""
    password_backend = PasswordBackend({
        DEMO_USERNAME: (Principal("demo-password", "固定账号 Demo"), hash_password(DEMO_PASSWORD)),
    })

    def demo_match(username: str, password: str) -> bool:
        # CallbackBackend has already validated UTF-8 shape.  Byte comparison
        # stays controlled for all Unicode accepted by that public contract.
        return hmac.compare_digest(username.encode("utf-8"), DEMO_USERNAME.encode("utf-8")) & hmac.compare_digest(
            password.encode("utf-8"), DEMO_PASSWORD.encode("utf-8")
        )

    def callback(username: str, password: str):
        valid = demo_match(username, password)
        return Principal("demo-callback", "同步回调 Demo") if valid else None

    async def async_callback(username: str, password: str):
        valid = demo_match(username, password)
        return Principal("demo-async", "异步回调 Demo") if valid else None

    demo_script = f"/assets/demo-login.js?v={__version__}"
    modes: dict[str, _Mode] = {}
    password_auth = _memory_auth(
        password_backend, origin=origin, mode="password",
        ui=LoginUI(
            title="固定账号登录",
            subtitle="使用演示账号体验默认登录界面。",
            script_url=demo_script, stylesheet_url=f"/assets/demo-login.css?v={__version__}",
            guest_url="/guest?mode=password",
        ),
    )
    modes["password"] = _Mode("password", "PasswordBackend", "默认 LoginUI", password_auth)
    callback_auth = _memory_auth(
        CallbackBackend(callback), origin=origin, mode="callback",
        ui=LoginUI(
            title="自定义页面登录",
            subtitle="保留你的页面，复用登录与会话能力。",
            renderer=_host_override,
        ),
    )
    modes["callback"] = _Mode("callback", "CallbackBackend", "宿主 renderer 覆盖", callback_auth)
    async_auth = _memory_auth(AsyncCallbackBackend(async_callback), origin=origin, mode="async", ui=None)
    modes["async"] = _Mode("async", "AsyncCallbackBackend", "Headless HTML/JS", async_auth)

    keeper, connect = _chatvoice_fixture()
    fixture_lock = threading.RLock()
    chatvoice = ChatVoiceAuth(
        connect, lambda: fixture_lock, time.time,
        ttl=DEMO_TTL_SECONDS, max_sessions=DEMO_MAX_SESSIONS,
    )
    chatvoice_auth = FastAPIAuth(
        chatvoice.backend,
        chatvoice.manager,
        origin=origin,
        prefix="/demo/chatvoice",
        ui=LoginUI(
            title="账户库兼容登录",
            subtitle="演示已有账户库接入，不连接真实数据。",
            palette="amber", layout="split", appearance="dark", script_url=demo_script, stylesheet_url=f"/assets/demo-login.css?v={__version__}",
        ),
        cookie=CookieSettings(
            name="chatlogin_demo_chatvoice", path="/", max_age=DEMO_TTL_SECONDS,
            secure=urlsplit(origin).scheme == "https", same_site="strict",
        ),
    )
    modes["chatvoice"] = _Mode("chatvoice", "ChatVoiceAuth", "LoginUI split", chatvoice_auth)

    # FastAPIAuth performs the strict syntax/canonical-origin validation.
    normalized_origin = password_auth.origin
    authority = urlsplit(normalized_origin).netloc.lower()
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            keeper.close()

    app = FastAPI(
        title="ChatLogin Demo", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(_FixedHostMiddleware, authority=authority)
    app.state.demo_origin = normalized_origin
    app.state.demo_modes = modes
    app.state.demo_chatvoice_keeper = keeper
    for mode in modes.values():
        app.include_router(mode.auth.router)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return _page(_replace(_resource("templates", "home.html"), VERSION=__version__))

    @app.get("/health")
    async def health():
        return _json({"status": "ok", "version": __version__})

    @app.get("/version")
    async def version():
        return _json({"version": __version__})

    @app.get("/assets/{name}")
    async def asset(name: str):
        media_type = _ASSETS.get(name)
        if media_type is None:
            raise HTTPException(404, "Asset not found")
        data = (resources.files("chatlogin.demo_site") / "assets" / name).read_bytes()
        return Response(data, media_type=media_type, headers={
            "Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff",
        })

    @app.get("/experience/async", response_class=HTMLResponse)
    async def headless():
        return _page(_replace(
            _resource("templates", "headless.html"),
            USERNAME=DEMO_USERNAME, PASSWORD=DEMO_PASSWORD,
        ))

    @app.get("/templates", response_class=HTMLResponse)
    async def templates():
        return _page(_resource("templates", "templates.html"), frame=True)

    @app.get("/playground/preview", response_class=HTMLResponse)
    async def preview(
        palette: str = "indigo", layout: str = "card", appearance: str = "system", guest: int = 0,
    ):
        if palette not in PALETTES or layout not in LAYOUTS or appearance not in APPEARANCES or guest not in {0, 1}:
            raise HTTPException(400, "Unsupported preview choice")
        ui = LoginUI(
            title="示例应用登录", subtitle="登录后继续演示体验。",
            palette=palette, layout=layout, appearance=appearance,
            guest_url="/guest?mode=password" if guest else None,
            script_url=demo_script, stylesheet_url=f"/assets/demo-login.css?v={__version__}",
        )
        html = ui.render({
            "login_url": "/demo/password/login", "session_url": "/demo/password/session",
            "logout_url": "/demo/password/logout", "assets_path": "/demo/password/assets",
            "next": "/workspace/password",
        })
        return _page(html, frame=True)

    def selected(mode: str) -> _Mode:
        result = modes.get(mode)
        if result is None:
            raise HTTPException(404, "Unknown demo mode")
        return result

    def login_route(mode: str) -> str:
        return "/experience/async" if mode == "async" else f"/demo/{mode}/?next=/workspace/{mode}"

    @app.get("/workspace/{mode}", response_class=HTMLResponse)
    async def workspace(mode: str, request: Request):
        current = selected(mode)
        session = current.auth.sessions.resolve(request.cookies.get(current.auth.cookie.name))
        principal = session.principal if session else None
        state = "authenticated" if principal else "guest"
        user_id = principal.user_id if principal else "—"
        display_name = principal.display_name if principal else "访客 / Guest"
        role = principal.role.value if principal else "guest"
        html = _replace(
            _resource("templates", "workspace.html"),
            MODE=mode, STATE=state, USER_ID=user_id, DISPLAY_NAME=display_name, ROLE=role,
            BACKEND=current.backend_label, UI=current.ui_label, LOGIN_ROUTE=login_route(mode),
        )
        return _page(html, frame=True)

    @app.get("/guest", response_class=HTMLResponse)
    async def guest(mode: str = "password"):
        current = selected(mode)
        html = _replace(
            _resource("templates", "workspace.html"),
            MODE=mode, STATE="guest", USER_ID="—", DISPLAY_NAME="访客 / Guest", ROLE="guest",
            BACKEND=current.backend_label, UI=current.ui_label, LOGIN_ROUTE=login_route(mode),
        )
        return _page(html, frame=True)

    @app.get("/api/demo/{mode}/protected")
    async def protected(mode: str, request: Request):
        current = selected(mode)
        principal = await current.auth.current_user(request)
        return _json({
            "ok": True, "user": principal.as_dict(),
            "backend": current.backend_label, "ui": current.ui_label,
        })

    @app.post("/api/demo/{mode}/csrf-check")
    async def csrf_check(mode: str, request: Request):
        current = selected(mode)
        principal = await current.auth.csrf_user(request)
        return _json({"ok": True, "user_id": principal.user_id, "action": "synthetic-check"})

    return app


__all__ = ["DEMO_PASSWORD", "DEMO_USERNAME", "DEMO_MAX_SESSIONS", "DEMO_TTL_SECONDS", "create_demo_app"]
