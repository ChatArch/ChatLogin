"""Installed-resource demo site and security-boundary contracts."""
from importlib import resources

import pytest
from fastapi.testclient import TestClient

from chatlogin import __version__


@pytest.fixture(scope="module")
def demo_client():
    from chatlogin.demo import DEMO_PASSWORD, DEMO_USERNAME, create_demo_app

    origin = "http://demo.test"
    with TestClient(create_demo_app(origin=origin), base_url=origin) as client:
        yield client, origin, DEMO_USERNAME, DEMO_PASSWORD


def test_demo_resources_are_packaged_and_public_pages_are_real(demo_client):
    client, _, _, _ = demo_client
    for name in ("home.html", "headless.html", "templates.html"):
        assert (resources.files("chatlogin.demo_site") / "templates" / name).is_file()

    home = client.get("/")
    assert home.status_code == 200
    assert "ChatLogin" in home.text and "四种真实后端" in home.text
    assert "OAuth" in home.text and "不提供" in home.text
    assert home.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in home.headers["content-security-policy"]
    assert client.get("/health").json() == {"status": "ok", "version": __version__}
    assert client.get("/version").json() == {"version": __version__}
    assert "text/css" in client.get("/assets/demo.css").headers["content-type"]
    assert "javascript" in client.get("/assets/demo.js").headers["content-type"]
    script = client.get("/assets/demo.js").text
    assert script.index('/demo/async/session') < script.index('/demo/async/login')
    assert 'headers["X-CSRF-Token"]' in script
    assert "localStorage" not in script and "sessionStorage" not in script
    assert client.get("/assets/not-present.js").status_code == 404


@pytest.mark.parametrize(
    ("mode", "page", "marker"),
    [
        ("password", "/demo/password/", 'class="chatlogin__form"'),
        ("callback", "/demo/callback/", "host-override"),
        ("async", "/experience/async", "headless-login"),
        ("chatvoice", "/demo/chatvoice/", 'data-layout="split"'),
    ],
)
def test_every_backend_and_frontend_mode_has_a_real_page(demo_client, mode, page, marker):
    client, _, _, _ = demo_client
    response = client.get(page)
    assert response.status_code == 200
    assert marker in response.text
    assert "Fill Demo" in response.text or "demo-login.js" in response.text
    assert f"/workspace/{mode}" in response.text


@pytest.mark.parametrize("mode", ["password", "callback", "async", "chatvoice"])
def test_real_login_protected_csrf_logout_flow(demo_client, mode):
    client, origin, username, password = demo_client
    client.cookies.clear()
    protected = f"/api/demo/{mode}/protected"
    action = f"/api/demo/{mode}/csrf-check"
    auth = f"/demo/{mode}"

    assert client.get(protected).status_code == 401
    bad = client.post(f"{auth}/login", headers={"Origin": origin}, json={"username": username, "password": "wrong"})
    assert bad.status_code == 401
    login = client.post(
        f"{auth}/login",
        headers={"Origin": origin},
        json={"username": username, "password": password, "next": f"/workspace/{mode}"},
    )
    assert login.status_code == 200
    payload = login.json()
    assert payload["user"]["user_id"].startswith("demo-")
    assert password not in login.text and "chatlogin_demo_" not in login.text
    assert client.get(protected).status_code == 200
    assert client.post(action, headers={"Origin": origin}).status_code == 403
    assert client.post(action, headers={"Origin": origin, "X-CSRF-Token": payload["csrf_token"]}).json()["ok"] is True
    workspace = client.get(f"/workspace/{mode}")
    assert payload["user"]["user_id"] in workspace.text
    assert password not in workspace.text and payload["csrf_token"] not in workspace.text
    assert client.post(f"{auth}/logout", headers={"Origin": origin, "X-CSRF-Token": payload["csrf_token"]}).status_code == 200
    assert client.get(protected).status_code == 401


def test_demo_sessions_are_cross_mode_isolated_and_origin_is_fixed(demo_client):
    client, origin, username, password = demo_client
    client.cookies.clear()
    login = client.post(
        "/demo/password/login",
        headers={"Origin": origin},
        json={"username": username, "password": password},
    )
    assert login.status_code == 200
    assert client.get("/api/demo/password/protected").status_code == 200
    assert client.get("/api/demo/callback/protected").status_code == 401
    assert client.post(
        "/demo/callback/login",
        headers={"Origin": "https://untrusted.invalid"},
        json={"username": username, "password": password},
    ).status_code == 403
    assert client.get("/health", headers={"Host": "untrusted.invalid"}).status_code == 400


@pytest.mark.parametrize("mode", ["callback", "async"])
def test_synthetic_callbacks_reject_unicode_credentials_without_server_error(demo_client, mode):
    client, origin, _, _ = demo_client
    client.cookies.clear()
    response = client.post(
        f"/demo/{mode}/login",
        headers={"Origin": origin},
        json={"username": "演示用户", "password": "错误口令"},
    )
    assert response.status_code == 401


def test_headless_repeat_login_refresh_logout_and_return_route(demo_client):
    client, origin, username, password = demo_client
    client.cookies.clear()
    body = {"username": username, "password": password, "next": "/workspace/async"}
    first = client.post("/demo/async/login", headers={"Origin": origin}, json=body)
    assert first.status_code == 200
    assert client.post("/demo/async/login", headers={"Origin": origin}, json=body).status_code == 403
    session = client.get("/demo/async/session").json()
    repeated = client.post(
        "/demo/async/login",
        headers={"Origin": origin, "X-CSRF-Token": session["csrf_token"]},
        json=body,
    )
    assert repeated.status_code == 200
    refreshed = client.get("/workspace/async")
    assert refreshed.status_code == 200 and "/experience/async" in refreshed.text
    csrf = client.get("/demo/async/session").json()["csrf_token"]
    assert client.post(
        "/demo/async/logout", headers={"Origin": origin, "X-CSRF-Token": csrf},
    ).status_code == 200
    guest = client.get("/workspace/async")
    assert "访客 / Guest" in guest.text and "/experience/async" in guest.text


def test_template_playground_uses_login_ui_and_bounded_choices(demo_client):
    client, _, _, _ = demo_client
    page = client.get("/templates")
    assert page.status_code == 200
    assert "3 × 2" in page.text and "LoginUI(" in page.text
    preview = client.get("/playground/preview?palette=forest&layout=split&appearance=dark&guest=1")
    assert preview.status_code == 200
    assert 'data-palette="forest"' in preview.text
    assert 'data-layout="split"' in preview.text
    assert 'data-appearance="dark"' in preview.text
    assert "访客" in preview.text
    assert client.get("/playground/preview?palette=unknown").status_code == 400
