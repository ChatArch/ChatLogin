"""Optional FastAPI adapter for ChatLogin's reusable auth core."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Iterable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .credentials import CredentialBackend, valid_credentials
from .identity import AccessDenied, Principal, Role, require_role, require_user
from .security import LoginRateLimiter, require_csrf, safe_next
from .sessions import SessionManager
from .ui import LoginUI

_COOKIE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_ALLOWED_ASSETS = {"login.css": "text/css; charset=utf-8", "login.js": "application/javascript; charset=utf-8"}


@dataclass(frozen=True)
class CookieSettings:
    name: str = "chatlogin_session"
    path: str = "/"
    max_age: int = 86_400
    secure: bool = True
    same_site: str = "lax"
    http_only: bool = True

    def __post_init__(self) -> None:
        same_site = self.same_site.lower()
        object.__setattr__(self, "same_site", same_site)
        if not _COOKIE_RE.fullmatch(self.name):
            raise ValueError("Cookie name is not safe")
        if not self.path.startswith("/") or any(ord(c) < 33 for c in self.path):
            raise ValueError("Cookie path must be a local absolute path")
        if self.max_age <= 0:
            raise ValueError("Cookie max_age must be positive")
        if same_site not in {"lax", "strict", "none"}:
            raise ValueError("same_site must be lax, strict or none")
        if same_site == "none" and not self.secure:
            raise ValueError("SameSite=None cookies must be Secure")
        if self.name.startswith("__Host-") and (not self.secure or self.path != "/"):
            raise ValueError("__Host- cookies require Secure and Path=/")


class FastAPIAuth:
    """Mountable JSON/headless auth routes plus optional packaged login UI."""

    def __init__(
        self,
        backend: CredentialBackend,
        sessions: SessionManager,
        *,
        origin: str,
        prefix: str = "/auth",
        ui: LoginUI | None = None,
        allow_native: bool = False,
        limiter: LoginRateLimiter | None = None,
        cookie: CookieSettings | None = None,
        max_body_bytes: int = 4096,
    ) -> None:
        self.backend = backend
        self.sessions = sessions
        self.origin = _validated_origin(origin)
        self.host = urlsplit(self.origin).netloc.lower()
        self.ui = ui
        self.allow_native = allow_native
        self.limiter = limiter
        self.cookie = cookie or CookieSettings()
        if max_body_bytes < 128 or max_body_bytes > 1_000_000:
            raise ValueError("max_body_bytes must be bounded")
        self.max_body_bytes = max_body_bytes
        self.prefix = "/" + prefix.strip("/")
        self.router = APIRouter(prefix=self.prefix)
        self._install_routes()

    def _install_routes(self) -> None:
        self.router.add_api_route("/session", self.session, methods=["GET"])
        self.router.add_api_route("/login", self.login, methods=["POST"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"])
        if self.ui is not None:
            self.router.add_api_route("/", self.login_page, methods=["GET"], response_class=HTMLResponse)
            self.router.add_api_route("/assets/{name}", self.asset, methods=["GET"])

    def _check_same_origin(self, request: Request, *, native_login: bool = False) -> None:
        if request.headers.get("host", "").lower() != self.host:
            raise HTTPException(status_code=400, detail="Invalid Host header")
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        if origin == self.origin and fetch_site not in {"cross-site", "same-site"}:
            return
        if native_login and self.allow_native and origin is None and request.headers.get("x-chatlogin-client") == "native":
            return
        raise HTTPException(status_code=403, detail="Same-origin request required")

    def _response(self, payload: dict, status_code: int = 200) -> JSONResponse:
        response = JSONResponse(payload, status_code=status_code)
        _no_store(response)
        return response

    def _client_key(self, request: Request, username: str) -> str:
        host = request.client.host if request.client else "unknown"
        return f"{host}:{username[:80]}"

    async def _json_body(self, request: Request) -> dict:
        body = await request.body()
        if len(body) > self.max_body_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid JSON") from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON object required")
        extra = set(payload) - {"username", "password", "next"}
        if extra:
            raise HTTPException(status_code=400, detail="Unsupported login fields")
        username = payload.get("username")
        password = payload.get("password")
        if not valid_credentials(username, password):
            raise HTTPException(status_code=400, detail="Invalid credential shape")
        return payload

    async def login(self, request: Request) -> JSONResponse:
        self._check_same_origin(request, native_login=True)
        payload = await self._json_body(request)
        username = payload["username"]
        if self.limiter is not None and not self.limiter.allow(self._client_key(request, username)):
            raise HTTPException(status_code=429, detail="Too many login attempts")
        previous_token = request.cookies.get(self.cookie.name)
        previous = self.sessions.resolve(previous_token)
        if previous is not None:
            try:
                require_csrf(previous, request.headers.get("x-csrf-token"))
            except AccessDenied as exc:
                _raise_http(exc)
        principal = self.backend.authenticate(username, payload["password"])
        if principal is None:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        issued = self.sessions.issue(principal, previous_token=previous_token if previous is not None else None)
        response = self._response({
            "authenticated": True,
            "user": principal.as_dict(),
            "csrf_token": issued.session.csrf_token,
            "next": safe_next(payload.get("next")),
        })
        response.set_cookie(
            self.cookie.name,
            issued.token,
            max_age=self.cookie.max_age,
            httponly=self.cookie.http_only,
            secure=self.cookie.secure,
            samesite=self.cookie.same_site,
            path=self.cookie.path,
        )
        return response

    async def session(self, request: Request) -> JSONResponse:
        session = self.sessions.resolve(request.cookies.get(self.cookie.name))
        if session is None:
            return self._response({"authenticated": False, "user": None, "csrf_token": None})
        return self._response({"authenticated": True, "user": session.principal.as_dict(), "csrf_token": session.csrf_token})

    async def logout(self, request: Request) -> JSONResponse:
        self._check_same_origin(request)
        session = self.sessions.resolve(request.cookies.get(self.cookie.name))
        if session is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            require_csrf(session, request.headers.get("x-csrf-token"))
        except AccessDenied as exc:
            _raise_http(exc)
        token = request.cookies.get(self.cookie.name)
        self.sessions.revoke(token)
        response = self._response({"authenticated": False})
        response.delete_cookie(self.cookie.name, path=self.cookie.path)
        return response

    async def current_user(self, request: Request) -> Principal:
        session = self.sessions.resolve(request.cookies.get(self.cookie.name))
        if session is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        return session.principal

    async def csrf_user(self, request: Request) -> Principal:
        self._check_same_origin(request)
        session = self.sessions.resolve(request.cookies.get(self.cookie.name))
        if session is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        try:
            require_csrf(session, request.headers.get("x-csrf-token"))
        except AccessDenied as exc:
            _raise_http(exc)
        return session.principal

    def roles(self, *roles: Role):
        async def dependency(principal: Principal = Depends(self.current_user)) -> Principal:
            try:
                return require_role(principal, *roles)
            except AccessDenied as exc:
                _raise_http(exc)
        return dependency

    async def login_page(self, request: Request, next: str | None = None) -> HTMLResponse:
        assert self.ui is not None
        context = {
            "login_url": f"{self.prefix}/login",
            "session_url": f"{self.prefix}/session",
            "logout_url": f"{self.prefix}/logout",
            "assets_path": f"{self.prefix}/assets",
            "next": safe_next(next),
        }
        response = HTMLResponse(self.ui.render(context))
        _no_store(response)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    async def asset(self, name: str) -> Response:
        content_type = _ALLOWED_ASSETS.get(name)
        if content_type is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        data = (resources.files("chatlogin.web") / "assets" / name).read_bytes()
        return Response(data, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})


def _validated_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise ValueError("origin must be an http(s) origin without path")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.hostname in {None, "*"}:
        raise ValueError("origin must not contain credentials, query, fragment or wildcard host")
    if origin in {"null", "*"}:
        raise ValueError("origin must be concrete")
    return f"{parsed.scheme}://{parsed.netloc}"


def _raise_http(exc: AccessDenied) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
