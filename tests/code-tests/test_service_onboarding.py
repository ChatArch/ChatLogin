"""Public discovery and account navigation through real ASGI requests."""
import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from chatlogin import CallbackBackend, ManagedUsers, MemorySessionStore, Principal, Role, SessionManager
from chatlogin.fastapi import FastAPIAuth
from chatlogin.managed_web import create_managed_auth
from chatlogin.ui import LoginUI


ORIGIN = "https://accounts.example.test"


def test_base_discovery_is_truthful_and_host_checked():
    backend = CallbackBackend(lambda username, password: Principal("base-user", "Base User") if password == "test-password" else None)
    auth = FastAPIAuth(backend, SessionManager(MemorySessionStore(), instance="onboarding"), origin=ORIGIN, prefix="/admin")
    app = FastAPI()
    app.include_router(auth.router)
    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get("/admin/api")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        manifest = response.json()
        assert manifest["version"] == "0.2.1"
        assert manifest["capabilities"]["managed_users"] is False
        assert manifest["pages"] == {}
        assert {("GET", "/admin/session"), ("POST", "/admin/login"), ("POST", "/admin/logout")} <= {
            (operation["method"], operation["path"]) for operation in manifest["operations"]
        }
        rejected = client.get("/admin/api", headers={"Host": "evil.test"})
        assert rejected.status_code == 400
        assert rejected.headers["cache-control"] == "no-store"
        assert not any(key in str(manifest).lower() for key in ("csrf", "cookie", "password", "token", "state/"))
        assert hasattr(auth, "navigation_from_request")


def test_managed_mount_headless_and_roles():
    users = ManagedUsers.in_memory("onboarding-managed")
    users.bootstrap_owner("owner", "owner-password")
    owner = users.authenticate("owner", "owner-password")
    users.create_user(owner, "member", "member-password", role=Role.USER, display_name="<Member>")
    auth = create_managed_auth("onboarding-managed", origin=ORIGIN, users=users, prefix="/admin")
    child = FastAPI()
    child.include_router(auth.router)
    @child.get("/navigation")
    async def navigation(request: Request):
        return await auth.navigation_from_request(request)
    app = FastAPI()
    app.mount("/tools", child)
    with TestClient(app, base_url=ORIGIN) as member_client, TestClient(app, base_url=ORIGIN) as owner_client:
        manifest = member_client.get("/tools/admin/api", headers={"X-Forwarded-Prefix": "/evil"}).json()
        assert manifest["capabilities"]["managed_users"] is True
        assert manifest["pages"]["users"] == "/tools/admin/users"
        assert member_client.get("/tools/admin/api", headers={"Host": "evil.test"}).status_code == 400
        assert member_client.get("/tools/admin/api").headers["cache-control"] == "no-store"
        assert {(item["method"], item["path"]) for item in manifest["operations"]} == {
            (method, "/tools" + route.path) for route in auth.router.routes
            if isinstance(route, APIRoute) for method in route.methods
        }
        assert ("PATCH", "/tools/admin/api/users/{user_id}") in {
            (operation["method"], operation["path"]) for operation in manifest["operations"]
        }
        assert "/evil" not in str(manifest)
        assert member_client.post("/tools/admin/login", json={"username": "member", "password": "member-password"}, headers={"Origin": ORIGIN}).status_code == 200
        page = member_client.get("/tools/admin/profile")
        assert page.status_code == 200
        assert 'class="chatlogin-account-menu' in page.text
        assert 'class="chatlogin-account-menu__link" href="/tools/admin/users"' not in page.text
        assert "&lt;Member&gt;" in page.text
        stylesheet = member_client.get("/tools/admin/assets/account-menu.css")
        assert stylesheet.status_code == 200
        assert "chatlogin-account-menu" in stylesheet.text
        assert {link["url"] for link in member_client.get("/tools/navigation").json()["links"]} == {"/tools/admin/profile"}
        owner_client.post("/tools/admin/login", json={"username": "owner", "password": "owner-password"}, headers={"Origin": ORIGIN})
        assert "/tools/admin/users" in owner_client.get("/tools/admin/profile").text
        record = next(user for user in owner_client.get("/tools/admin/api/users").json()["users"] if user["username"] == "member")
        csrf = owner_client.get("/tools/admin/session").json()["csrf_token"]
        assert owner_client.patch(f"/tools/admin/api/users/{record['user_id']}", json={"role": "admin"}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
        assert {link["url"] for link in member_client.get("/tools/navigation").json()["links"]} == {"/tools/admin/"}
    headless = create_managed_auth("onboarding-managed", origin=ORIGIN, users=users, pages=False)
    headless_app = FastAPI()
    headless_app.include_router(headless.router)
    with TestClient(headless_app, base_url=ORIGIN) as client:
        assert client.get("/auth/api").json()["pages"] == {}
        assert client.get("/auth/profile").status_code == 404
        assert client.get("/auth/assets/account-menu.css").status_code == 404


def test_menu_modes_escape_and_override(tmp_path):
    from chatlogin.account_ui import AccountMenuUI
    context = {"identity": "<script>x</script>", "links": [{"label": "<Profile>", "url": "/auth/profile"}], "assets_path": "/auth/assets"}
    gear = AccountMenuUI().render(context)
    assert "<details" in gear and "<script>x</script>" not in gear
    assert "&lt;Profile&gt;" in gear and 'href="/auth/profile"' in gear
    assert 'href="/auth/assets/account-menu.css"' in gear
    assert AccountMenuUI(mode="links").render(context).count("<details") == 0
    template = tmp_path / "custom.html"
    template.write_text("{{ identity }}", encoding="utf-8")
    assert "&lt;script&gt;" in AccountMenuUI(template_dirs=[tmp_path], template_name="custom.html").render(context)
    assert AccountMenuUI(renderer=lambda data: "CUSTOM").render(context) == "CUSTOM"
    with pytest.raises(ValueError):
        AccountMenuUI().render({**context, "links": [{"label": "unsafe", "url": "//evil.test"}]})


def test_new_service_factory_real_login_and_management():
    from examples.managed_service import create_app

    users = ManagedUsers.in_memory("example-onboarding")
    users.bootstrap_owner("operator", "operator-password")
    app = create_app(instance="example-onboarding", origin=ORIGIN, users=users, prefix="/admin")
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/admin/api").json()["pages"]["users"] == "/admin/users"
        assert client.get("/private").status_code == 401
        result = client.post("/admin/login", json={"username": "operator", "password": "operator-password"}, headers={"Origin": ORIGIN})
        assert result.status_code == 200
        assert client.get("/private").status_code == 200
        assert client.get("/").status_code == 200
        created = client.post("/admin/api/users", json={"username": "someone", "password": "new-password", "role": "user"}, headers={"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]})
        assert created.status_code == 201
        assert any(user["username"] == "someone" for user in client.get("/admin/api/users").json()["users"])
        with TestClient(app, base_url=ORIGIN) as member_client:
            assert member_client.post("/admin/login", json={"username": "someone", "password": "new-password"}, headers={"Origin": ORIGIN}).status_code == 200
            assert member_client.get("/operator").status_code == 403
            assert member_client.get("/admin/api/users").status_code == 403
            assert 'href="/admin/users"' not in member_client.get("/").text
            record = next(user for user in client.get("/admin/api/users").json()["users"] if user["username"] == "someone")
            changed = client.patch(f"/admin/api/users/{record['user_id']}", json={"enabled": False}, headers={"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]})
            assert changed.status_code == 200
            assert member_client.get("/admin/session").json()["authenticated"] is False
            headers = {"Origin": ORIGIN, "X-CSRF-Token": result.json()["csrf_token"]}
            assert client.patch(f"/admin/api/users/{record['user_id']}", json={"enabled": True}, headers=headers).status_code == 200
            assert client.post(f"/admin/api/users/{record['user_id']}/password", json={"new_password": "updated-password"}, headers=headers).status_code == 200
            assert member_client.post("/admin/login", json={"username": "someone", "password": "new-password"}, headers={"Origin": ORIGIN}).status_code == 401
            assert member_client.post("/admin/login", json={"username": "someone", "password": "updated-password"}, headers={"Origin": ORIGIN}).status_code == 200
            assert client.delete(f"/admin/api/users/{record['user_id']}", headers=headers).json() == {"deleted": True}
            assert member_client.get("/admin/session").json()["authenticated"] is False


def test_managed_demo_reuses_role_aware_menu():
    from chatlogin.managed_demo import create_managed_demo_app

    with TestClient(create_managed_demo_app(origin=ORIGIN), base_url=ORIGIN) as client:
        assert 'href="/auth/users"' not in client.get("/").text
        assert 'href="/auth/"' in client.get("/").text
        assert client.post("/auth/login", json={"username": "managed-user", "password": "public-user-demo"}, headers={"Origin": ORIGIN}).status_code == 200
        assert 'href="/auth/profile"' in client.get("/").text
        assert 'href="/auth/users"' not in client.get("/").text
