"""Origin equivalence and real ASGI mount regressions (synthetic identities)."""
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chatlogin as cl
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

BODY = {"username": "one", "password": "test-password"}


def application(origin, **kwargs):
    auth = FastAPIAuth(
        cl.CallbackBackend(lambda u, p: cl.Principal("u1", "Synthetic")),
        cl.SessionManager(cl.MemorySessionStore(), instance="origin-mount"),
        origin=origin, **kwargs,
    )
    app = FastAPI()
    app.include_router(auth.router)
    return auth, app


@pytest.mark.parametrize("scheme,port", [("http", 80), ("https", 443)])
@pytest.mark.parametrize("configured_port", [False, True])
@pytest.mark.parametrize("host_port", [None, False, True])
@pytest.mark.parametrize("origin_port", [False, True])
def test_default_port_browser_equivalence(scheme, port, configured_port, host_port, origin_port):
    origin = f"{scheme}://example.test"
    auth, app = application(origin + (f":{port}" if configured_port else ""))
    headers = {"Origin": origin + (f":{port}" if origin_port else "")}
    if host_port is not None:
        headers["Host"] = "example.test" + (f":{port}" if host_port else "")
    with TestClient(app, base_url=origin) as client:
        response = client.post("/auth/login", json=BODY, headers=headers)
        assert response.status_code == 200, response.text
        assert client.get("/auth/session", headers={k: v for k, v in headers.items() if k == "Host"}).status_code == 200
    assert auth.origin == origin
    assert auth.cookie.path == "/"


@pytest.mark.parametrize("headers,status", [
    ({"Host": "example.test:444", "Origin": "https://example.test"}, 400),
    ({"Origin": "https://example.test:444"}, 403),
    ({"Origin": "http://example.test:80"}, 403),
    ({"Origin": "https://evil.test:443"}, 403),
    ({"Origin": "https://example.test/"}, 403),
    ({"Origin": "https://example.test/path"}, 403),
    ({"Origin": "https://example.test?x"}, 403),
    ({"Origin": "https://example.test#x"}, 403),
    ({"Origin": "https://user@example.test"}, 403),
    ({"Host": "example.test/", "Origin": "https://example.test"}, 400),
    ({"Host": "evil.test", "Origin": "https://example.test", "X-Forwarded-Host": "example.test:443"}, 400),
    ({"Origin": "https://evil.test", "Forwarded": "host=example.test;proto=https"}, 403),
    ({"Origin": "https://example.test", "Sec-Fetch-Site": "cross-site"}, 403),
    ([("Host", "example.test"), ("Host", "example.test:443"), ("Origin", "https://example.test")], 400),
    ([("Origin", "https://example.test"), ("Origin", "https://example.test:443")], 403),
])
def test_origin_guards_remain_strict(headers, status):
    _, app = application("https://example.test")
    with TestClient(app, base_url="https://example.test") as client:
        response = client.post("/auth/login", json=BODY, headers=headers)
        assert response.status_code == status
        assert "set-cookie" not in response.headers


@pytest.mark.parametrize("host,origin,status", [
    ("example.test:8443", "https://example.test:8443", 200),
    ("example.test", "https://example.test:8443", 400),
    ("example.test:8443", "https://example.test", 403),
    ("example.test:8443", "https://example.test:443", 403),
])
def test_nondefault_port_is_distinct(host, origin, status):
    _, app = application("https://example.test:8443")
    with TestClient(app, base_url="https://example.test:8443") as client:
        assert client.post("/auth/login", json=BODY, headers={"Host": host, "Origin": origin}).status_code == status


@pytest.mark.parametrize("mount", ["/tools", "/outer/tools"])
def test_mounted_page_links_assets_and_auth_roundtrip(mount):
    origin = "https://example.test"
    contexts = []

    def render(context):
        contexts.append(context)
        return LoginUI(guest_url="/guest").render(context)

    auth, child = application(origin, ui=LoginUI(guest_url="/guest", renderer=render), cookie=CookieSettings(path=mount + "/auth"))
    parent = FastAPI()
    parent.mount(mount, child)
    with TestClient(parent, base_url=origin) as client:
        page = client.get(mount + "/auth/", headers={"X-Forwarded-Prefix": "/evil", "Forwarded": "host=evil.test"})
        assert page.status_code == 200
        for endpoint in ("login", "session", "logout"):
            assert contexts[0][endpoint + "_url"] == f"{mount}/auth/{endpoint}"
        for endpoint in ("login", "session"):
            assert f'{mount}/auth/{endpoint}' in page.text
        assert 'href="/guest"' in page.text
        assert "/evil" not in page.text
        assets = re.findall(r'(?:href|src)="([^"]+/assets/login\.(?:css|js))"', page.text)
        assert set(assets) == {f"{mount}/auth/assets/login.css", f"{mount}/auth/assets/login.js"}
        for asset in assets:
            assert client.get(asset).status_code == 200
        login = client.post(mount + "/auth/login", json=BODY, headers={"Origin": origin})
        assert login.status_code == 200
        assert f"Path={mount}/auth" in login.headers["set-cookie"]
        session = client.get(mount + "/auth/session")
        assert session.json()["authenticated"] is True
        logout = client.post(mount + "/auth/logout", headers={"Origin": origin, "X-CSRF-Token": login.json()["csrf_token"]})
        assert logout.status_code == 200
        assert client.get(mount + "/auth/session").json()["authenticated"] is False
    assert auth.cookie.path == mount + "/auth"
