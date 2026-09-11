"""Optional FastAPI adapter for ChatLogin's reusable auth core."""
from __future__ import annotations

import json
import re
import inspect
from dataclasses import dataclass
from importlib import resources
from ipaddress import IPv6Address
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .credentials import AsyncCredentialBackend, CredentialBackend, valid_credentials
from .identity import AccessDenied, Principal, Role, require_role
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
        if not isinstance(self.same_site, str):
            raise ValueError("same_site must be a string")
        same_site = self.same_site.lower()
        object.__setattr__(self, "same_site", same_site)
        if not isinstance(self.name, str) or not _COOKIE_RE.fullmatch(self.name):
            raise ValueError("Cookie name is not safe")
        _validated_path(self.path)
        if type(self.max_age) is not int or self.max_age <= 0:
            raise ValueError("Cookie max_age must be positive")
        if type(self.secure) is not bool or type(self.http_only) is not bool:
            raise ValueError("Cookie flags must be booleans")
        if same_site not in {"lax", "strict", "none"}:
            raise ValueError("same_site must be lax, strict or none")
        if same_site == "none" and not self.secure:
            raise ValueError("SameSite=None cookies must be Secure")
        if self.name.startswith("__Host-") and (not self.secure or self.path != "/"):
            raise ValueError("__Host- cookies require Secure and Path=/")
        if self.name.startswith("__Secure-") and not self.secure:
            raise ValueError("__Secure- cookies require Secure")


class FastAPIAuth:
    """Mountable JSON/headless auth routes plus optional packaged login UI."""

    def __init__(
        self,
        backend: CredentialBackend | AsyncCredentialBackend,
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
        if type(allow_native) is not bool:
            raise ValueError("allow_native must be a boolean")
        if cookie is not None and not isinstance(cookie, CookieSettings):
            raise ValueError("cookie must be CookieSettings")
        self.backend = backend
        self.sessions = sessions
        self.origin = _validated_origin(origin)
        self.host = urlsplit(self.origin).netloc.lower()
        self.ui = ui
        self.allow_native = allow_native
        self.limiter = limiter if limiter is not None else LoginRateLimiter()
        self.cookie = cookie or CookieSettings()
        if type(max_body_bytes) is not int or max_body_bytes < 128 or max_body_bytes > 1_000_000:
            raise ValueError("max_body_bytes must be bounded")
        self.max_body_bytes = max_body_bytes
        self.prefix = _validated_path(prefix).rstrip("/")
        self.router = APIRouter(prefix=self.prefix)
        self._install_routes()

    def _install_routes(self) -> None:
        self.router.add_api_route("/session", self.session, methods=["GET"])
        self.router.add_api_route("/login", self.login, methods=["POST"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"])
        if self.ui is not None:
            self.router.add_api_route("/", self.login_page, methods=["GET"], response_class=HTMLResponse)
            self.router.add_api_route("/assets/{name}", self.asset, methods=["GET"])

    def _check_host(self, request: Request) -> None:
        hosts = request.headers.getlist("host")
        try:
            host_origin = _validated_origin(
                f"{urlsplit(self.origin).scheme}://{hosts[0]}", allow_trailing_slash=False,
            ) if len(hosts) == 1 else None
        except ValueError:
            host_origin = None
        if host_origin != self.origin:
            raise _http(status_code=400, detail="Invalid Host header")

    def _check_same_origin(self, request: Request, *, native_login: bool = False) -> None:
        self._check_host(request)
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        try:
            normalized_origin = _validated_origin(origin, allow_trailing_slash=False)
        except ValueError:
            normalized_origin = None
        if len(request.headers.getlist("origin")) == 1 and normalized_origin == self.origin and fetch_site in {None, "same-origin", "none"}:
            return
        if (native_login and self.allow_native and origin is None
                and self.cookie.name not in request.cookies
                and fetch_site in {None, "none"}
                and request.headers.get("x-chatlogin-client") == "native"):
            return
        raise _http(status_code=403, detail="Same-origin request required")

    def _response(self, payload: dict, status_code: int = 200) -> JSONResponse:
        response = JSONResponse(payload, status_code=status_code)
        _no_store(response)
        return response

    def _client_key(self, request: Request) -> str:
        # Only the ASGI peer address: never username or arbitrary forwarded headers.
        return request.client.host if request.client else "unknown"

    async def _json_body(self, request: Request) -> dict:
        content_types = request.headers.getlist("content-type")
        if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().lower() != "application/json":
            raise _http(status_code=415, detail="Content-Type must be application/json")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > self.max_body_bytes:
                raise _http(status_code=413, detail="Request body too large")
            body.extend(chunk)
        try:
            payload = json.loads(body.decode("utf-8"), object_pairs_hook=_json_object, parse_constant=_invalid_json)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _http(status_code=400, detail="Invalid JSON") from None
        if not isinstance(payload, dict):
            raise _http(status_code=400, detail="JSON object required")
        extra = set(payload) - {"username", "password", "next"}
        if extra:
            raise _http(status_code=400, detail="Unsupported login fields")
        username = payload.get("username")
        password = payload.get("password")
        if not valid_credentials(username, password):
            raise _http(status_code=400, detail="Invalid credential shape")
        if payload.get("next") is not None and not isinstance(payload["next"], str):
            raise _http(status_code=400, detail="Invalid next shape")
        try:
            (payload.get("next") or "").encode("utf-8")
        except UnicodeEncodeError:
            raise _http(status_code=400, detail="Invalid next encoding") from None
        return payload

    async def login(self, request: Request) -> JSONResponse:
        self._check_same_origin(request, native_login=True)
        payload = await self._json_body(request)
        username = payload["username"]
        if not await _call(self.limiter.allow, self._client_key(request)):
            raise _http(status_code=429, detail="Too many login attempts")
        previous_token = request.cookies.get(self.cookie.name)
        previous = await _call(self.sessions.resolve, previous_token)
        if previous is not None:
            try:
                require_csrf(previous, request.headers.get("x-csrf-token"))
            except AccessDenied as exc:
                _raise_http(exc)
        principal = await _call(self.backend.authenticate, username, payload["password"])
        if principal is None:
            raise _http(status_code=401, detail="Invalid username or password")
        issued = await _call(self.sessions.issue, principal, previous_token=previous_token if previous is not None else None)
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
        self._check_host(request)
        session = await _call(self.sessions.resolve, request.cookies.get(self.cookie.name))
        if session is None:
            return self._response({"authenticated": False, "user": None, "csrf_token": None})
        return self._response({"authenticated": True, "user": session.principal.as_dict(), "csrf_token": session.csrf_token})

    async def logout(self, request: Request) -> JSONResponse:
        self._check_same_origin(request)
        session = await _call(self.sessions.resolve, request.cookies.get(self.cookie.name))
        if session is None:
            raise _http(status_code=401, detail="Authentication required")
        try:
            require_csrf(session, request.headers.get("x-csrf-token"))
        except AccessDenied as exc:
            _raise_http(exc)
        token = request.cookies.get(self.cookie.name)
        await _call(self.sessions.revoke, token)
        response = self._response({"authenticated": False})
        response.delete_cookie(self.cookie.name, path=self.cookie.path,
                               secure=self.cookie.secure, httponly=self.cookie.http_only,
                               samesite=self.cookie.same_site)
        return response

    async def current_user(self, request: Request) -> Principal:
        self._check_host(request)
        session = await _call(self.sessions.resolve, request.cookies.get(self.cookie.name))
        if session is None:
            raise _http(status_code=401, detail="Authentication required")
        return session.principal

    async def csrf_user(self, request: Request) -> Principal:
        self._check_same_origin(request)
        session = await _call(self.sessions.resolve, request.cookies.get(self.cookie.name))
        if session is None:
            raise _http(status_code=401, detail="Authentication required")
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
        # ASGI mount/deployment metadata is trusted; forwarded headers are not.
        prefix = request.scope.get("root_path", "").rstrip("/") + self.prefix
        context = {
            "login_url": f"{prefix}/login",
            "session_url": f"{prefix}/session",
            "logout_url": f"{prefix}/logout",
            "assets_path": f"{prefix}/assets",
            "next": safe_next(next),
        }
        response = HTMLResponse(self.ui.render(context))
        _no_store(response)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response

    async def asset(self, name: str) -> Response:
        content_type = _ALLOWED_ASSETS.get(name)
        if content_type is None:
            raise _http(status_code=404, detail="Asset not found")
        data = (resources.files("chatlogin.web") / "assets" / name).read_bytes()
        return Response(data, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})


def _validated_origin(origin: str, *, allow_trailing_slash: bool = True) -> str:
    if (not isinstance(origin, str) or not origin
            or any(ord(c) < 33 or ord(c) > 126 for c in origin)
            or any(c in origin for c in "\\?#%@")):
        raise ValueError("origin must be a concrete ASCII http(s) origin")
    parsed = urlsplit(origin)
    paths = {"", "/"} if allow_trailing_slash else {""}
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in paths:
        raise ValueError("origin must be an http(s) origin without path")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.hostname in {None, "*"}:
        raise ValueError("origin must not contain credentials, query, fragment or wildcard host")
    port = parsed.port  # Raises ValueError for invalid or out-of-range ports.
    if parsed.netloc.endswith(":") or port == 0:
        raise ValueError("origin port must be valid")
    host = parsed.hostname
    if ":" in host:
        IPv6Address(host)
        authority = f"[{host}]"
    else:
        if len(host) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split(".")):
            raise ValueError("origin hostname is invalid")
        authority = host
    if port is not None:
        authority += f":{port}"
    if parsed.netloc.lower() != authority:
        raise ValueError("origin authority must be canonical")
    # Validate the supplied authority before applying browser origin equivalence.
    if port == {"http": 80, "https": 443}[parsed.scheme]:
        authority = authority.rsplit(":", 1)[0]
    return f"{parsed.scheme}://{authority}"


def _validated_path(path: str) -> str:
    if (not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9._~/-]*", path)
            or "//" in path or any(part in {".", ".."} for part in path.split("/"))):
        raise ValueError("Path must be a safe local absolute path")
    return path


def _json_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _invalid_json(value: str):
    raise ValueError("Invalid JSON constant")


async def _call(function, *args, **kwargs):
    """Run sync core off-loop and await async adapters without exposing exceptions."""
    try:
        if inspect.iscoroutinefunction(function):
            return await function(*args, **kwargs)
        result = await run_in_threadpool(function, *args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    except Exception:
        raise _http(500, "Authentication service unavailable") from None


def _http(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail,
                         headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _raise_http(exc: AccessDenied) -> None:
    raise _http(status_code=exc.status_code, detail=exc.detail)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
