import importlib
import json
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import chatlogin as cl


def test_web_module_is_available():
    assert importlib.util.find_spec("chatlogin.fastapi") is not None, "Optional FastAPI adapter must exist"


@pytest.fixture
def web():
    # Import within tests: a missing optional adapter is a behavior failure.
    return importlib.import_module("chatlogin.fastapi")


def application(web, *, ui=None, native=False, limiter=None, cookie=None, backend=None):
    user = cl.Principal("u1", "Synthetic <User>")
    backend = backend or cl.CallbackBackend(lambda u, p: user if (u, p) == ("one", "test-password") else None)
    auth = web.FastAPIAuth(backend, cl.SessionManager(cl.MemorySessionStore(), instance="example"),
                          origin="https://example.test", prefix="/api/auth", ui=ui,
                          allow_native=native, limiter=limiter, cookie=cookie)
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/private")
    async def private(principal=Depends(auth.current_user)):
        return principal.as_dict()

    @app.post("/write")
    async def write(principal=Depends(auth.csrf_user)):
        return {"owner": principal.user_id}

    @app.get("/admin")
    async def admin(principal=Depends(auth.roles(cl.Role.ADMIN))):
        return principal.as_dict()

    return auth, TestClient(app, base_url="https://example.test")


def login(client, **extra):
    return client.post("/api/auth/login", json={"username": "one", "password": "test-password", **extra},
                       headers={"Origin": "https://example.test"})


def test_json_login_cookie_session_csrf_logout_and_permissions(web):
    auth, client = application(web)
    assert client.get("/api/auth/session").json() == {"authenticated": False, "user": None, "csrf_token": None}
    assert client.get("/private").status_code == 401
    result = login(client, next="//evil.test")
    assert result.status_code == 200
    assert result.json()["next"] == "/"
    assert result.json()["user"]["role"] == "user"
    assert "token" not in result.json()
    cookie = result.headers["set-cookie"]
    for item in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=86400"):
        assert item in cookie
    assert result.headers["cache-control"] == "no-store"
    assert client.get("/private").json()["user_id"] == "u1"
    assert client.get("/admin").status_code == 403
    csrf = client.get("/api/auth/session").json()["csrf_token"]
    assert csrf == result.json()["csrf_token"]
    origin = {"Origin": "https://example.test"}
    assert client.post("/write", headers=origin).status_code == 403
    assert client.post("/write", headers={**origin, "X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/write", headers={**origin, "X-CSRF-Token": csrf}).status_code == 200
    assert client.post("/api/auth/logout", headers=origin).status_code == 403
    assert client.post("/api/auth/logout", headers={**origin, "X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/private").status_code == 401
    assert client.get("/api/auth/session").json()["authenticated"] is False


def test_json_login_accepts_async_credential_backend(web):
    user = cl.Principal("async-web-user", "Async Web")

    async def authenticate(username, password):
        return user if (username, password) == ("one", "test-password") else None

    _, client = application(web, backend=cl.AsyncCallbackBackend(authenticate))
    result = login(client)
    assert result.status_code == 200
    assert result.json()["user"]["user_id"] == "async-web-user"


def test_login_rotation_requires_csrf_for_existing_cookie(web):
    auth, client = application(web)
    first = login(client)
    old = client.cookies.get(auth.cookie.name)
    assert login(client).status_code == 403
    second = client.post("/api/auth/login", json={"username": "one", "password": "test-password"},
                         headers={"Origin": "https://example.test", "X-CSRF-Token": first.json()["csrf_token"]})
    assert second.status_code == 200
    assert client.cookies.get(auth.cookie.name) != old
    assert auth.sessions.resolve(old) is None


@pytest.mark.parametrize("headers", [
    {}, {"Origin": "https://evil.test"}, {"Origin": "null"},
    {"Origin": "https://example.test.evil.test"},
    {"Origin": "https://example.test", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://example.test", "Host": "evil.test"},
    {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "example.test", "Host": "evil.test"},
])
def test_origin_and_host_fail_closed(web, headers):
    _, client = application(web)
    result = client.post("/api/auth/login", json={"username": "one", "password": "test-password"}, headers=headers)
    assert result.status_code in (400, 403)
    assert "set-cookie" not in result.headers
    assert "access-control-allow-origin" not in result.headers


def test_native_clients_are_opt_in_and_cookie_writes_still_require_csrf(web):
    _, client = application(web, native=True)
    result = client.post("/api/auth/login", json={"username": "one", "password": "test-password"},
                         headers={"X-ChatLogin-Client": "native"})
    assert result.status_code == 200
    assert client.post("/write", headers={"X-ChatLogin-Client": "native"}).status_code == 403
    # Native clients with a cookie must explicitly send canonical Origin AND CSRF.
    assert client.post("/write", headers={"X-ChatLogin-Client": "native", "X-CSRF-Token": result.json()["csrf_token"]}).status_code == 403
    _, closed = application(web)
    assert closed.post("/api/auth/login", json={"username": "one", "password": "test-password"}, headers={"X-ChatLogin-Client": "native"}).status_code == 403


def test_uniform_bad_credentials_bounded_bodies_and_rate_limit(web):
    _, client = application(web)
    errors = []
    for u, p in [("unknown", "test-password"), ("one", "wrong")]:
        r = client.post("/api/auth/login", json={"username": u, "password": p}, headers={"Origin": "https://example.test"})
        assert r.status_code == 401
        errors.append(r.json())
    assert errors[0] == errors[1]
    origin = {"Origin": "https://example.test", "Content-Type": "application/json"}
    for payload in (b"x" * 4097, [b"x" * 2048, b"x" * 2049]):
        assert client.post("/api/auth/login", content=iter(payload) if isinstance(payload, list) else payload, headers=origin).status_code == 413
    for body in ({"username": "one", "password": "x" * 1025}, {"username": "x" * 257, "password": "pw"}, [], {"username": None}, {"username": "one", "password": "test-password", "role": "admin"}):
        assert client.post("/api/auth/login", json=body, headers=origin).status_code == 400
    _, limited = application(web, limiter=cl.LoginRateLimiter(limit=1))
    assert login(limited).status_code == 200
    assert login(limited).status_code == 429


def test_config_cookie_proxy_and_same_origin_validation(web):
    with pytest.raises(ValueError):
        web.CookieSettings(same_site="none", secure=False)
    with pytest.raises(ValueError):
        web.CookieSettings(name="unsafe;cookie")
    with pytest.raises(ValueError):
        web.CookieSettings(name="__Host-demo", secure=False)
    backend = cl.CallbackBackend(lambda u, p: None)
    sessions = cl.SessionManager(cl.MemorySessionStore(), instance="isolated")
    for bad in ("*", "https://good.test/path", "https://user:password@good.test", "null"):
        with pytest.raises(ValueError):
            web.FastAPIAuth(backend, sessions, origin=bad)
    cookie = web.CookieSettings(name="host_cookie", path="/api", secure=False, same_site="strict")
    auth, client = application(web, cookie=cookie)
    result = login(client)
    assert "Secure" not in result.headers["set-cookie"]
    assert "Path=/api" in result.headers["set-cookie"]
    assert "SameSite=strict" in result.headers["set-cookie"]


def test_headless_registers_no_page_assets_or_cors(web):
    auth, client = application(web)
    assert client.get("/api/auth/").status_code == 404
    assert client.get("/api/auth/assets/login.css").status_code == 404
    response = client.options("/api/auth/login", headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in response.headers
    assert not any("assets" in getattr(r, "path", "") for r in auth.router.routes)


def test_default_palettes_layouts_scoped_css_and_html_escaping(web):
    ui_module = importlib.import_module("chatlogin.ui")
    for palette in ("indigo", "forest", "amber"):
        for layout in ("card", "split"):
            _, client = application(web, ui=ui_module.LoginUI(title='<script>alert("bad")</script>', subtitle="<img src=x>", palette=palette, layout=layout))
            result = client.get('/api/auth/?next=%22%3E%3Cscript%3Ebad%3C/script%3E')
            assert result.status_code == 200
            assert "<script>alert" not in result.text and "&lt;script&gt;" in result.text
            assert '<img src=x>' not in result.text
            assert f'data-palette="{palette}"' in result.text
            assert f'data-layout="{layout}"' in result.text
            assert 'data-login-url="/api/auth/login"' in result.text
            assert 'data-next="/"' in result.text
            assert 'script-src \'self\'' in result.headers["content-security-policy"]
    css = client.get("/api/auth/assets/login.css")
    script = client.get("/api/auth/assets/login.js")
    assert css.status_code == script.status_code == 200
    assert ".chatlogin" in css.text and "--cl-" in css.text
    assert ":root" not in css.text and "@media" in css.text
    assert "localStorage" not in script.text
    assert "textContent" in script.text and "credentials" in script.text
    assert client.get("/api/auth/assets/missing.js").status_code == 404
    with pytest.raises(ValueError):
        ui_module.LoginUI(palette="missing")


def test_host_partial_whole_renderer_and_custom_stylesheet_overrides(web, tmp_path):
    UI = importlib.import_module("chatlogin.ui").LoginUI
    (tmp_path / "custom.html").write_text('{% extends "chatlogin/login.html" %}{% block branding %}<h1>Host {{ title }}</h1>{% endblock %}')
    _, client = application(web, ui=UI(title="<unsafe>", template_dirs=[tmp_path], template_name="custom.html", stylesheet_url="/host.css"))
    text = client.get("/api/auth/").text
    assert "Host &lt;unsafe&gt;" in text and 'name="password"' in text
    assert 'href="/host.css"' in text
    (tmp_path / "whole.html").write_text("<h1>Whole {{ title }}</h1>")
    _, client = application(web, ui=UI(title="<unsafe>", template_dirs=[tmp_path], template_name="whole.html"))
    assert client.get("/api/auth/").text == "<h1>Whole &lt;unsafe&gt;</h1>"
    _, client = application(web, ui=UI(renderer=lambda context: "<h1>Host renderer</h1>"))
    assert client.get("/api/auth/").text == "<h1>Host renderer</h1>"
