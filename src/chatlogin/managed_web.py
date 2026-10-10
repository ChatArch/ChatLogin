"""Optional FastAPI preset for the managed-user service.

This module intentionally contains only HTTP, rendering and browser-facing
validation. Account policy and persistence always stay in ``chatlogin.managed``.
"""
from __future__ import annotations

import inspect
from importlib import resources
from ipaddress import ip_address
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .fastapi import (
    CookieSettings,
    FastAPIAuth,
    _http,
    _json_object_body,
    _no_store,
    _raise_http,
    _validated_origin,
)
from .identity import AccessDenied, Principal, Role, require_role
from .sessions import StoreFull
from .ui import LoginUI
from .user_ui import UserAdminUI, UserProfileUI

if TYPE_CHECKING:  # pragma: no cover - supplied by the independently-owned core lane.
    from .managed import ManagedUsers, UserRecord


_MANAGED_ASSETS = {
    "users.css": "text/css; charset=utf-8",
    "users.js": "application/javascript; charset=utf-8",
}
_MANAGED_BODY_MAX = 8192


def _managed_users_type():
    """Resolve the core only when a managed preset is actually constructed."""
    try:
        from .managed import ManagedUsers
    except ImportError as exc:  # Keep the optional Web module importable during staged integration.
        raise RuntimeError("Managed-user core is unavailable; integrate chatlogin.managed before constructing ManagedAuth") from exc
    return ManagedUsers


def _is_loopback_origin(origin: str) -> bool:
    host = urlsplit(origin).hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _managed_cookie(
    origin: str,
    cookie: CookieSettings | None,
    *,
    allow_insecure_loopback: bool,
    namespace: str,
) -> CookieSettings:
    if type(allow_insecure_loopback) is not bool:
        raise ValueError("allow_insecure_loopback must be a boolean")
    normalized = _validated_origin(origin)
    scheme = urlsplit(normalized).scheme
    loopback = _is_loopback_origin(normalized)
    if scheme == "http" and (not allow_insecure_loopback or not loopback):
        raise ValueError("HTTP managed authentication requires explicit loopback convenience")
    if cookie is None:
        return CookieSettings(name=f"chatlogin_{namespace}_session", secure=scheme == "https")
    if not isinstance(cookie, CookieSettings):
        raise ValueError("cookie must be CookieSettings")
    if not cookie.secure and (scheme != "http" or not loopback or not allow_insecure_loopback):
        raise ValueError("Insecure managed cookies are only allowed for explicit loopback HTTP")
    return cookie


class ManagedAuth(FastAPIAuth):
    """Managed-user login, profile, administration and asset routes.

    ``users`` is the single real ``ManagedUsers`` service object. No account
    policy is mirrored here: every record operation is delegated to that object.
    """

    def __init__(
        self,
        users: "ManagedUsers",
        *,
        origin: str,
        prefix: str = "/auth",
        ui: LoginUI | None = None,
        pages: bool = True,
        admin_ui: UserAdminUI | None = None,
        profile_ui: UserProfileUI | None = None,
        cookie: CookieSettings | None = None,
        allow_native: bool = False,
        allow_insecure_loopback: bool = False,
        limiter=None,
        login_max_body_bytes: int = 4096,
        managed_max_body_bytes: int = _MANAGED_BODY_MAX,
    ) -> None:
        if type(pages) is not bool:
            raise ValueError("pages must be boolean")
        self.pages = pages
        managed_type = _managed_users_type()
        if not isinstance(users, managed_type):
            raise TypeError("users must be a ManagedUsers service")
        if type(managed_max_body_bytes) is not int or not 128 <= managed_max_body_bytes <= _MANAGED_BODY_MAX:
            raise ValueError("managed_max_body_bytes must be between 128 and 8192")
        login_ui = ui if ui is not None else LoginUI()
        if not isinstance(login_ui, LoginUI):
            raise TypeError("ui must be LoginUI")
        if admin_ui is not None and not isinstance(admin_ui, UserAdminUI):
            raise TypeError("admin_ui must be UserAdminUI")
        if profile_ui is not None and not isinstance(profile_ui, UserProfileUI):
            raise TypeError("profile_ui must be UserProfileUI")
        self.users = users
        self.admin_ui = admin_ui if admin_ui is not None else UserAdminUI(login_ui=login_ui)
        self.profile_ui = profile_ui if profile_ui is not None else UserProfileUI(login_ui=login_ui)
        self.managed_max_body_bytes = managed_max_body_bytes
        super().__init__(
            users,
            users.sessions,
            origin=origin,
            prefix=prefix,
            ui=login_ui if pages else None,
            allow_native=allow_native,
            limiter=limiter,
            cookie=_managed_cookie(origin, cookie, allow_insecure_loopback=allow_insecure_loopback, namespace=users.session_namespace),
            max_body_bytes=login_max_body_bytes,
        )

    def _install_routes(self) -> None:
        super()._install_routes()
        if self.pages:
            self.router.add_api_route("/users", self.users_page, methods=["GET"], response_class=HTMLResponse)
            self.router.add_api_route("/profile", self.profile_page, methods=["GET"], response_class=HTMLResponse)
        self.router.add_api_route("/api/users", self.users_api, methods=["GET"])
        self.router.add_api_route("/api/users", self.create_user_api, methods=["POST"])
        self.router.add_api_route("/api/users/{user_id}/password", self.reset_user_password_api, methods=["POST"])
        self.router.add_api_route("/api/users/{user_id}", self.user_api, methods=["GET"])
        self.router.add_api_route("/api/users/{user_id}", self.update_user_api, methods=["PATCH"])
        self.router.add_api_route("/api/users/{user_id}", self.delete_user_api, methods=["DELETE"])
        self.router.add_api_route("/api/profile", self.profile_api, methods=["GET"])
        self.router.add_api_route("/api/profile", self.update_profile_api, methods=["PATCH"])
        self.router.add_api_route("/api/profile/password", self.change_profile_password_api, methods=["POST"])
        self.router.add_api_route("/api/owner/transfer", self.transfer_owner_api, methods=["POST"])

    async def asset(self, name: str) -> Response:
        content_type = _MANAGED_ASSETS.get(name)
        if content_type is None:
            return await super().asset(name)
        data = (resources.files("chatlogin.web") / "assets" / name).read_bytes()
        return Response(data, media_type=content_type, headers={"Cache-Control": "public, max-age=3600"})

    async def admin_user(self, request: Request) -> Principal:
        actor = await self.current_user(request)
        try:
            from .identity import require_admin
        except ImportError:
            raise _http(503, "Managed-user authorization is unavailable") from None
        try:
            return require_admin(actor)
        except AccessDenied as exc:
            _raise_http(exc)

    async def owner_user(self, request: Request) -> Principal:
        actor = await self.current_user(request)
        try:
            owner = Role.OWNER
        except AttributeError:
            raise _http(503, "Managed-user authorization is unavailable") from None
        try:
            return require_role(actor, owner)
        except AccessDenied as exc:
            _raise_http(exc)

    async def _managed_call(self, function, *args, **kwargs):
        """Call trusted core methods without turning policy errors into 500s."""
        try:
            if inspect.iscoroutinefunction(function):
                return await function(*args, **kwargs)
            result = await run_in_threadpool(function, *args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        except AccessDenied as exc:
            _raise_http(exc)
        except StoreFull:
            raise _http(503, "Session capacity exhausted; retry after active sessions expire") from None
        except (TypeError, ValueError):
            raise _http(400, "Invalid managed-user request") from None
        except Exception as exc:
            # The managed core may expose a controlled status exception. Its
            # status is trusted by module provenance, but its detail is never
            # reflected so storage or credential data cannot leak through HTTP.
            status = getattr(exc, "status_code", None)
            if exc.__class__.__module__ == "chatlogin.managed" and type(status) is int and 400 <= status <= 599:
                raise _http(status, _managed_status_detail(status)) from None
            raise _http(500, "Managed-user service unavailable") from None

    async def _management_json(self, request: Request, allowed_fields: set[str]) -> dict:
        return await _json_object_body(
            request,
            max_body_bytes=self.managed_max_body_bytes,
            allowed_fields=allowed_fields,
            unsupported_detail="Unsupported managed-user fields",
        )

    def _mount_prefix(self, request: Request) -> str:
        root_path = request.scope.get("root_path", "")
        # root_path is trusted ASGI mount metadata; forwarded headers are ignored.
        return root_path.rstrip("/") + self.prefix

    def _page_context(self, request: Request) -> dict[str, str]:
        prefix = self._mount_prefix(request)
        return {
            "assets_path": f"{prefix}/assets",
            "login_url": f"{prefix}/",
            "session_url": f"{prefix}/session",
            "logout_url": f"{prefix}/logout",
            "users_url": f"{prefix}/users",
            "profile_url": f"{prefix}/profile",
            "users_api_url": f"{prefix}/api/users",
            "profile_api_url": f"{prefix}/api/profile",
            "owner_transfer_api_url": f"{prefix}/api/owner/transfer",
        }

    def _login_redirect(self, request: Request, suffix: str) -> RedirectResponse:
        prefix = self._mount_prefix(request)
        target = f"{prefix}{suffix}"
        response = RedirectResponse(f"{prefix}/?next={quote(target, safe='/')}", status_code=303)
        _no_store(response)
        return response

    async def users_page(self, request: Request) -> Response:
        try:
            await self.admin_user(request)
        except HTTPException as exc:
            if exc.status_code == 401:
                return self._login_redirect(request, "/users")
            raise
        response = HTMLResponse(self.admin_ui.render(self._page_context(request)))
        _private_html(response)
        return response

    async def profile_page(self, request: Request) -> Response:
        try:
            await self.current_user(request)
        except HTTPException as exc:
            if exc.status_code == 401:
                return self._login_redirect(request, "/profile")
            raise
        response = HTMLResponse(self.profile_ui.render(self._page_context(request)))
        _private_html(response)
        return response

    async def users_api(self, request: Request) -> JSONResponse:
        actor = await self.admin_user(request)
        offset, limit = _pagination(request)
        records = await self._managed_call(self.users.list_users, actor, offset=offset, limit=limit)
        return self._response({"users": [_record_payload(record) for record in records]})

    async def create_user_api(self, request: Request) -> JSONResponse:
        actor = await self._admin_write_user(request)
        payload = await self._management_json(request, {"username", "password", "role", "display_name"})
        username = _required_text(payload, "username")
        password = _required_text(payload, "password")
        display_name = _optional_text(payload, "display_name", default="")
        role = _optional_role(payload)
        arguments: dict[str, Any] = {"display_name": display_name}
        if role is not None:
            arguments["role"] = role
        record = await self._managed_call(self.users.create_user, actor, username, password, **arguments)
        return self._response({"user": _record_payload(record)}, status_code=201)

    async def user_api(self, request: Request) -> JSONResponse:
        actor = await self.admin_user(request)
        record = await self._managed_call(self.users.get_user, actor, _path_user_id(request))
        if record is None:
            raise _http(404, "Managed user not found")
        return self._response({"user": _record_payload(record)})

    async def update_user_api(self, request: Request) -> JSONResponse:
        actor = await self._admin_write_user(request)
        payload = await self._management_json(request, {"display_name", "role", "enabled"})
        if not payload:
            raise _http(400, "At least one managed-user field is required")
        arguments: dict[str, Any] = {}
        if "display_name" in payload:
            arguments["display_name"] = _optional_text(payload, "display_name", default="")
        if "role" in payload:
            arguments["role"] = _required_role(payload["role"])
        if "enabled" in payload:
            if type(payload["enabled"]) is not bool:
                raise _http(400, "Invalid enabled shape")
            arguments["enabled"] = payload["enabled"]
        record = await self._managed_call(self.users.update_user, actor, _path_user_id(request), **arguments)
        return self._response({"user": _record_payload(record)})

    async def delete_user_api(self, request: Request) -> JSONResponse:
        actor = await self._admin_write_user(request)
        await self._managed_call(self.users.delete_user, actor, _path_user_id(request))
        return self._response({"deleted": True})

    async def reset_user_password_api(self, request: Request) -> JSONResponse:
        actor = await self._admin_write_user(request)
        payload = await self._management_json(request, {"new_password"})
        await self._managed_call(self.users.reset_password, actor, _path_user_id(request), _required_text(payload, "new_password"))
        return self._response({"password_reset": True})

    async def profile_api(self, request: Request) -> JSONResponse:
        actor = await self.current_user(request)
        record = await self._managed_call(self.users.current_user, actor)
        return self._response({"user": _record_payload(record)})

    async def update_profile_api(self, request: Request) -> JSONResponse:
        actor = await self._csrf_user(request)
        payload = await self._management_json(request, {"display_name"})
        if set(payload) != {"display_name"}:
            raise _http(400, "display_name is required")
        record = await self._managed_call(
            self.users.update_user,
            actor,
            actor.user_id,
            display_name=_optional_text(payload, "display_name", default=""),
        )
        return self._response({"user": _record_payload(record)})

    async def change_profile_password_api(self, request: Request) -> JSONResponse:
        actor = await self._csrf_user(request)
        payload = await self._management_json(request, {"current_password", "new_password"})
        current_password = _required_text(payload, "current_password")
        new_password = _required_text(payload, "new_password")
        await self._managed_call(self.users.change_password, actor, current_password, new_password)
        return self._response({"password_changed": True})

    async def transfer_owner_api(self, request: Request) -> JSONResponse:
        actor = await self._owner_write_user(request)
        payload = await self._management_json(request, {"target_user_id", "current_password", "confirm_username"})
        await self._managed_call(
            self.users.transfer_owner,
            actor,
            _required_text(payload, "target_user_id"),
            _required_text(payload, "current_password"),
            _required_text(payload, "confirm_username"),
        )
        return self._response({"transferred": True})

    async def _csrf_user(self, request: Request) -> Principal:
        return await self.csrf_user(request)

    async def _admin_write_user(self, request: Request) -> Principal:
        actor = await self._csrf_user(request)
        try:
            from .identity import require_admin
        except ImportError:
            raise _http(503, "Managed-user authorization is unavailable") from None
        try:
            return require_admin(actor)
        except AccessDenied as exc:
            _raise_http(exc)

    async def _owner_write_user(self, request: Request) -> Principal:
        actor = await self._csrf_user(request)
        try:
            owner = Role.OWNER
        except AttributeError:
            raise _http(503, "Managed-user authorization is unavailable") from None
        try:
            return require_role(actor, owner)
        except AccessDenied as exc:
            _raise_http(exc)


def create_managed_auth(
    instance: str,
    *,
    origin: str,
    home=None,
    users: "ManagedUsers | None" = None,
    prefix: str = "/auth",
    ui: LoginUI | None = None,
    pages: bool = True,
    admin_ui: UserAdminUI | None = None,
    profile_ui: UserProfileUI | None = None,
    cookie: CookieSettings | None = None,
    allow_native: bool = False,
    allow_insecure_loopback: bool = False,
    limiter=None,
    login_max_body_bytes: int = 4096,
    managed_max_body_bytes: int = _MANAGED_BODY_MAX,
) -> ManagedAuth:
    """Create one persistent managed-user service and its mounted FastAPI preset.

    ``instance`` and ``origin`` are deliberately required. HTTP is rejected
    unless the caller explicitly opts into an actual loopback development origin.
    """
    # Validate the externally supplied security boundary before opening or
    # creating an instance database through the core factory.
    from .paths import validate_instance
    instance = validate_instance(instance)
    validated_cookie = _managed_cookie(
        origin,
        cookie,
        allow_insecure_loopback=allow_insecure_loopback,
        namespace=instance,
    )
    managed_type = _managed_users_type()
    if users is None:
        users = managed_type.for_instance(instance, home=home)
    elif not isinstance(users, managed_type):
        raise TypeError("users must be a ManagedUsers service")
    elif users.session_namespace != instance:
        raise ValueError("Provided users must use the requested session namespace")
    elif home is not None:
        raise ValueError("home cannot override an explicitly provided managed service")
    return ManagedAuth(
        users,
        origin=origin,
        prefix=prefix,
        ui=ui,
        pages=pages,
        admin_ui=admin_ui,
        profile_ui=profile_ui,
        cookie=validated_cookie,
        allow_native=allow_native,
        allow_insecure_loopback=allow_insecure_loopback,
        limiter=limiter,
        login_max_body_bytes=login_max_body_bytes,
        managed_max_body_bytes=managed_max_body_bytes,
    )


def _managed_status_detail(status: int) -> str:
    if status == 401:
        return "Authentication required"
    if status == 403:
        return "Managed-user action not permitted"
    if status == 404:
        return "Managed user not found"
    if status == 409:
        return "Managed-user state changed; retry the request"
    if status == 429:
        return "Too many managed-user requests"
    if status == 503:
        return "Managed-user service unavailable"
    return "Invalid managed-user request" if 400 <= status < 500 else "Managed-user service unavailable"


def _private_html(response: HTMLResponse) -> None:
    _no_store(response)
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"


def _pagination(request: Request) -> tuple[int, int]:
    allowed = {"offset", "limit"}
    if set(request.query_params) - allowed:
        raise _http(400, "Unsupported pagination fields")
    values: dict[str, int] = {}
    for name, default, maximum in (("offset", 0, 1_000_000), ("limit", 100, 100)):
        items = request.query_params.getlist(name)
        if not items:
            values[name] = default
            continue
        if len(items) != 1 or not items[0].isdecimal():
            raise _http(400, "Invalid pagination")
        value = int(items[0])
        if value > maximum:
            raise _http(400, "Invalid pagination")
        values[name] = value
    return values["offset"], values["limit"]


def _path_user_id(request: Request) -> str:
    user_id = request.path_params.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise _http(400, "Invalid managed-user identifier")
    try:
        encoded = user_id.encode("utf-8")
    except UnicodeEncodeError:
        raise _http(400, "Invalid managed-user identifier") from None
    if len(encoded) > 512 or any(ord(character) < 33 or ord(character) == 127 for character in user_id):
        raise _http(400, "Invalid managed-user identifier")
    return user_id


def _utf8_text(value: object, *, field: str, allow_empty: bool) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise _http(400, f"Invalid {field} shape")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _http(400, f"Invalid {field} encoding") from None
    return value


def _required_text(payload: dict, field: str) -> str:
    if field not in payload:
        raise _http(400, f"{field} is required")
    return _utf8_text(payload[field], field=field, allow_empty=False)


def _optional_text(payload: dict, field: str, *, default: str) -> str:
    if field not in payload:
        return default
    return _utf8_text(payload[field], field=field, allow_empty=True)


def _required_role(value: object) -> Role:
    text = _utf8_text(value, field="role", allow_empty=False)
    try:
        return Role(text)
    except ValueError:
        raise _http(400, "Invalid role") from None


def _optional_role(payload: dict) -> Role | None:
    return _required_role(payload["role"]) if "role" in payload else None


def _record_payload(record: "UserRecord") -> dict[str, object]:
    """Serialize only the immutable safe record fields, never ``__dict__``."""
    role = getattr(record, "role")
    return {
        "user_id": _safe_scalar(getattr(record, "user_id")),
        "username": _safe_scalar(getattr(record, "username")),
        "display_name": _safe_scalar(getattr(record, "display_name")),
        "role": role.value if isinstance(role, Role) else _safe_scalar(role),
        "enabled": _safe_scalar(getattr(record, "enabled")),
        "deleted": _safe_scalar(getattr(record, "deleted")),
        "created_at": _safe_scalar(getattr(record, "created_at")),
        "updated_at": _safe_scalar(getattr(record, "updated_at")),
    }


def _safe_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


__all__ = ["ManagedAuth", "create_managed_auth"]
