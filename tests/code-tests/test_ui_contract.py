"""UI contracts; opt in to the bounded offline browser suite via env."""
import os
from pathlib import Path

import pytest

from chatlogin.ui import LoginUI

CONTEXT = {"assets_path": "/auth/assets", "login_url": "/auth/login",
           "session_url": "/auth/session", "next": "/private"}
ASSETS = Path(__file__).resolve().parents[2] / "src/chatlogin/web/assets"


@pytest.mark.parametrize("field", ["stylesheet_url", "script_url", "guest_url"])
@pytest.mark.parametrize("value", ["//evil.test/a", "/\\evil.test/a", "/%2fevil.test",
                                  "/%255cevil.test", "/a\n.css", "https://evil.test",
                                  "relative.css", "/a/../b", "/%2e%2e/b"])
def test_local_urls_reject_ambiguous_or_external_paths(field, value):
    with pytest.raises(ValueError):
        LoginUI(**{field: value})


@pytest.mark.parametrize("name", ["/etc/passwd", "../base.html", "a/../b.html",
                                 "a\\b.html", "", "a//b.html", "a\x00.html"])
def test_template_names_are_safe_relative_paths(name):
    with pytest.raises(ValueError):
        LoginUI(template_name=name)


def test_renderer_and_directory_validation(tmp_path):
    for bad in ("templates", Path("templates"), [123]):
        with pytest.raises((TypeError, ValueError)):
            LoginUI(template_dirs=bad)
    with pytest.raises((TypeError, ValueError)):
        LoginUI(renderer="not callable")
    with pytest.raises(TypeError):
        LoginUI(renderer=lambda context: None).render(CONTEXT)
    assert LoginUI(renderer=lambda context: "<b>trusted host HTML</b>").render(CONTEXT) == "<b>trusted host HTML</b>"


def test_defaults_and_guest_contract():
    html = LoginUI().render(CONTEXT)
    assert 'data-session-url="/auth/session"' in html
    assert 'class="chatlogin-page"' in html
    assert 'class="chatlogin__branding"' in html
    assert 'class="chatlogin__form-panel"' in html
    assert "登录后继续" in html
    assert 'class="chatlogin__guest"' not in html
    assert 'src="/host.js"' not in html
    html = LoginUI(script_url="/host.js").render(CONTEXT)
    assert '<script defer src="/host.js"></script>' in html
    html = LoginUI(guest_url="/guest?mode=read", guest_label="访客 <查看>").render(CONTEXT)
    assert 'href="/guest?mode=read"' in html
    assert "访客 &lt;查看&gt;" in html


@pytest.mark.parametrize("appearance", ["system", "light", "dark"])
def test_appearance_is_orthogonal(appearance):
    for palette in ("indigo", "forest", "amber"):
        for layout in ("card", "split"):
            html = LoginUI(appearance=appearance, palette=palette, layout=layout).render(CONTEXT)
            assert f'data-appearance="{appearance}"' in html
            assert f'data-palette="{palette}"' in html
            assert f'data-layout="{layout}"' in html
    with pytest.raises(ValueError):
        LoginUI(appearance="invalid")


@pytest.fixture(scope="module")
def browser():
    if os.environ.get("CHATLOGIN_BROWSER_TESTS") != "1":
        pytest.skip("opt-in offline Playwright smoke")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        owned = p.chromium.launch(headless=True)
        try:
            yield owned
        finally:
            owned.close()


def load_page(page, ui, *, status=401, network=False, preflight_status=200):
    calls = []
    def route(request):
        path = request.request.url.split("example.test", 1)[-1]
        if path == "/":
            request.fulfill(body=ui.render(CONTEXT), content_type="text/html")
        elif path.startswith("/auth/assets/"):
            name = path.rsplit("/", 1)[-1]
            request.fulfill(body=(ASSETS / name).read_text(), content_type="text/css" if name.endswith("css") else "application/javascript")
        elif path == "/auth/session":
            calls.append(("session", request.request))
            request.fulfill(status=preflight_status, json={"authenticated": True, "csrf_token": "synthetic-csrf"})
        elif path == "/auth/login":
            calls.append(("login", request.request))
            if network:
                request.abort()
            else:
                request.fulfill(status=status, json={"next": "/private"})
        elif path == "/host.css":
            request.fulfill(body="body { --cl-accent: rgb(17, 34, 51); }", content_type="text/css")
        else:
            request.fulfill(body="<h1>Destination</h1>", content_type="text/html")
    page.route("**/*", route)
    page.goto("https://example.test/")
    return calls


def test_browser_layout_and_inherited_host_tokens(browser):
    context = browser.new_context()
    try:
        page = context.new_page()
        load_page(page, LoginUI(layout="split", stylesheet_url="/host.css"))
        for width in (320, 390, 1280):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
            boxes = page.locator(".chatlogin__panel > *").evaluate_all("els => els.map(e => {const r=e.getBoundingClientRect(); return {x:r.x,y:r.y}})")
            assert len(boxes) == 2
            if width == 1280:
                assert boxes[0]["x"] < boxes[1]["x"] and boxes[0]["y"] == boxes[1]["y"]
        assert page.locator("button").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(17, 34, 51)"
        page.emulate_media(color_scheme="dark")
        assert page.locator(".chatlogin").evaluate("e => getComputedStyle(e).colorScheme") == "dark"
    finally:
        context.close()


@pytest.mark.parametrize("status,network,preflight_status,message", [
    (401, False, 200, "账号或密码"), (429, False, 200, "频繁"),
    (200, True, 200, "网络"), (200, False, 503, "服务"),
])
def test_browser_errors_csrf_and_double_submit(browser, status, network, preflight_status, message):
    context = browser.new_context()
    try:
        page = context.new_page()
        calls = load_page(page, LoginUI(), status=status, network=network, preflight_status=preflight_status)
        page.locator('[name="username"]').fill("synthetic-user")
        page.locator('[name="password"]').fill("synthetic-password")
        page.locator("form").evaluate("f => {f.requestSubmit(); f.requestSubmit();}")
        page.wait_for_function("text => document.querySelector('.chatlogin__status').textContent.includes(text)", arg=message, timeout=3000)
        assert page.locator("button").is_enabled()
        assert [kind for kind, _ in calls] == (["session", "login"] if preflight_status == 200 else ["session"])
        if preflight_status == 200:
            assert calls[-1][1].headers.get("x-csrf-token") == "synthetic-csrf"
        assert page.evaluate("localStorage.length + sessionStorage.length") == 0
    finally:
        context.close()


def test_browser_success_redirect(browser):
    context = browser.new_context()
    try:
        page = context.new_page()
        calls = load_page(page, LoginUI(), status=200)
        page.locator('[name="username"]').fill("synthetic-user")
        page.locator('[name="password"]').fill("synthetic-password")
        page.locator("button").click()
        page.wait_for_url("**/private", timeout=3000)
        assert [kind for kind, _ in calls] == ["session", "login"]
    finally:
        context.close()
