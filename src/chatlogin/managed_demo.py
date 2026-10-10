"""Disposable managed-users demonstration, loaded only by ``serve --managed-demo``.

The module deliberately keeps public synthetic credentials here rather than in
the managed core. Importing it requires no optional Web dependency; creating an
app does, and uses the real managed service and Web preset once those surfaces
are installed.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from html import escape
from importlib import resources
import inspect
from urllib.parse import urlsplit


DEMO_INSTANCE = "managed-demo"
DEMO_TTL_SECONDS = 300
DEMO_MAX_USERS = 16
DEMO_MAX_SESSIONS = 32


@dataclass(frozen=True)
class _PublicFixture:
    username: str
    password: str
    display_name: str
    role: str


# These credentials are intentionally public and exist only for this disposable
# demo factory. They are never defaults in the managed core or production setup.
_PUBLIC_FIXTURES = (
    _PublicFixture("managed-owner", "public-owner-demo", "Public Demo Owner", "owner"),
    _PublicFixture("managed-admin", "public-admin-demo", "Public Demo Admin", "admin"),
    _PublicFixture("managed-user", "public-user-demo", "Public Demo User", "user"),
)


def _fixture_payload() -> list[dict[str, str]]:
    return [
        {
            "username": fixture.username,
            "password": fixture.password,
            "display_name": fixture.display_name,
            "role": fixture.role,
        }
        for fixture in _PUBLIC_FIXTURES
    ]


def _render_landing(*, root_path: str) -> str:
    template = (resources.files("chatlogin.demo_site") / "templates" / "managed.html").read_text(encoding="utf-8")
    prefix = root_path.rstrip("/") + "/auth"
    links = {
        "LOGIN_URL": f"{prefix}/",
        "USERS_URL": f"{prefix}/users",
        "PROFILE_URL": f"{prefix}/profile",
    }
    fixtures = "".join(
        "<tr id=\"managed-demo-{}\"><td>{}</td><td><code>{}</code></td><td><code>{}</code></td></tr>".format(
            escape(fixture.role),
            escape(fixture.role),
            escape(fixture.username),
            escape(fixture.password),
        )
        for fixture in _PUBLIC_FIXTURES
    )
    links["FIXTURES"] = fixtures
    for name, value in links.items():
        template = template.replace("{{" + name + "}}", value)
    return template


def _close_in_memory_users(users) -> None:
    """Close the Core's explicit in-memory lifetime without owning its storage policy."""
    for target in (users, getattr(users, "store", None)):
        close = getattr(target, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                raise RuntimeError("Managed demo shutdown requires a synchronous close method")
            return
    raise RuntimeError("Managed demo requires an explicit close method for in-memory users")


def create_managed_demo_app(*, origin: str):
    """Build a real, in-memory managed-auth demo for one fixed browser origin."""
    # Optional imports stay here so CLI help/tree and core-only import remain light.
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    from . import __version__
    from .demo import _FixedHostMiddleware
    from .identity import Role
    from .managed import ManagedUsers
    from .managed_web import create_managed_auth

    try:
        owner_role = Role.OWNER
    except AttributeError as exc:
        raise RuntimeError("Managed demo requires the managed-users Core and Web integration") from exc

    users = ManagedUsers.in_memory(
        DEMO_INSTANCE,
        ttl=DEMO_TTL_SECONDS,
        max_users=DEMO_MAX_USERS,
        max_sessions=DEMO_MAX_SESSIONS,
    )
    owner, admin, member = _PUBLIC_FIXTURES
    try:
        users.bootstrap_owner(owner.username, owner.password, display_name=owner.display_name)
        actor = users.authenticate(owner.username, owner.password)
        if actor is None or actor.role is not owner_role:
            raise RuntimeError("Managed demo owner bootstrap did not authenticate")
        users.create_user(actor, admin.username, admin.password, role=Role.ADMIN, display_name=admin.display_name)
        users.create_user(actor, member.username, member.password, role=Role.USER, display_name=member.display_name)
        auth = create_managed_auth(instance=DEMO_INSTANCE, origin=origin, users=users, prefix="/auth", allow_insecure_loopback=True)
    except Exception:
        _close_in_memory_users(users)
        raise

    normalized_origin = auth.origin
    authority = urlsplit(normalized_origin).netloc.lower()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            _close_in_memory_users(users)

    app = FastAPI(
        title="ChatLogin Managed Demo",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(_FixedHostMiddleware, authority=authority)
    app.state.managed_demo_users = users
    app.state.managed_demo_auth = auth
    app.include_router(auth.router)

    def response(payload: dict) -> JSONResponse:
        result = JSONResponse(payload)
        result.headers["Cache-Control"] = "no-store"
        result.headers["Pragma"] = "no-cache"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    @app.get("/", response_class=HTMLResponse)
    async def landing(request: Request):
        page = HTMLResponse(_render_landing(root_path=request.scope.get("root_path", "")))
        page.headers["Cache-Control"] = "no-store"
        page.headers["Pragma"] = "no-cache"
        page.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
        )
        page.headers["X-Content-Type-Options"] = "nosniff"
        page.headers["Referrer-Policy"] = "no-referrer"
        return page

    @app.get("/health")
    async def health():
        return response({"version": __version__, "mode": "managed-demo", "synthetic": True})

    @app.get("/api/managed-demo/accounts")
    async def public_accounts():
        return response({"synthetic": True, "accounts": _fixture_payload()})

    return app


__all__ = [
    "DEMO_INSTANCE",
    "DEMO_MAX_SESSIONS",
    "DEMO_MAX_USERS",
    "DEMO_TTL_SECONDS",
    "create_managed_demo_app",
]
