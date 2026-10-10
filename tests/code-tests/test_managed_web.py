"""Managed FastAPI boundary contracts; gated on the separately-owned core lane."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chatlogin.identity import Role
from chatlogin.ui import LoginUI


managed = pytest.importorskip("chatlogin.managed", reason="managed core is supplied by the separate core lane")
from chatlogin.managed_web import ManagedAuth


ORIGIN = "https://managed.example.test"


def make_app():
    users = managed.ManagedUsers.in_memory("managed-web-tests")
    owner = users.bootstrap_owner("owner", "owner-password", "Owner")
    owner_actor = users.authenticate("owner", "owner-password")
    users.create_user(owner_actor, "admin", "admin-password", role=Role.ADMIN, display_name="Admin")
    users.create_user(owner_actor, "member", "member-password", display_name="Member")
    auth = ManagedAuth(users, origin=ORIGIN, prefix="/auth", ui=LoginUI())
    app = FastAPI()
    app.include_router(auth.router)
    return auth, users, owner, app


def login(client, username, password, *, prefix="/auth"):
    response = client.post(f"{prefix}/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def write_headers(csrf):
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def test_pages_routes_assets_and_mount_derive_urls_only_from_trusted_scope():
    _, _, _, child = make_app()
    app = FastAPI()
    app.mount("/tools", child)
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        anonymous = client.get("/tools/auth/users", headers={"X-Forwarded-Prefix": "/evil"})
        assert anonymous.status_code in (302, 303)
        assert anonymous.headers["location"] == "/tools/auth/?next=/tools/auth/users"
        assert "/evil" not in anonymous.headers["location"]
        csrf = login(client, "admin", "admin-password", prefix="/tools/auth")
        page = client.get("/tools/auth/users")
        assert page.status_code == 200
        for url in ("/tools/auth/session", "/tools/auth/profile", "/tools/auth/api/users", "/tools/auth/assets/users.css", "/tools/auth/assets/users.js"):
            assert url in page.text
        assert page.headers["cache-control"] == "no-store"
        assert client.get("/tools/auth/assets/users.css").status_code == 200
        assert client.get("/tools/auth/assets/users.js").status_code == 200
        assert csrf


def test_roles_csrf_origin_and_json_shape_are_server_enforced_before_body_parse():
    _, _, _, app = make_app()
    with TestClient(app, base_url=ORIGIN) as client:
        member_csrf = login(client, "member", "member-password")
        assert client.get("/auth/users").status_code == 403
        assert client.get("/auth/api/users").status_code == 403
        forged = client.post("/auth/api/users", json={"username": "forged", "password": "valid-password", "role": "admin"}, headers=write_headers(member_csrf))
        assert forged.status_code == 403

        client.post("/auth/logout", headers=write_headers(member_csrf))
        admin_csrf = login(client, "admin", "admin-password")
        missing_csrf = client.post("/auth/api/users", json={"username": "new-user", "password": "valid-password"}, headers={"Origin": ORIGIN})
        assert missing_csrf.status_code == 403
        for raw in (
            '{"username":"new-user","password":"valid-password","actor":"owner"}',
            '{"username":"new-user","username":"duplicate","password":"valid-password"}',
            '{"username":"new-user","password":NaN}',
        ):
            response = client.post("/auth/api/users", content=raw, headers={**write_headers(admin_csrf), "Content-Type": "application/json"})
            assert response.status_code == 400
            assert response.headers["cache-control"] == "no-store"
        oversized = client.post("/auth/api/users", content=b"x" * 8193, headers={**write_headers(admin_csrf), "Content-Type": "application/json"})
        assert oversized.status_code == 413
        cross_origin = client.post("/auth/api/users", content=b"x" * 8193, headers={"Origin": "https://evil.example.test", "Content-Type": "application/json"})
        assert cross_origin.status_code == 403
        wrong_host = client.post("/auth/api/users", content=b"x" * 8193, headers={**write_headers(admin_csrf), "Host": "evil.example.test", "Content-Type": "application/json"})
        assert wrong_host.status_code == 400


def test_profile_is_self_only_and_core_session_invalidation_cannot_leave_admin_access():
    auth, users, _, app = make_app()
    with TestClient(app, base_url=ORIGIN) as owner_client, TestClient(app, base_url=ORIGIN) as admin_client:
        owner_csrf = login(owner_client, "owner", "owner-password")
        admin_csrf = login(admin_client, "admin", "admin-password")
        own_profile = admin_client.get("/auth/api/profile")
        assert own_profile.status_code == 200
        assert own_profile.json()["user"]["username"] == "admin"
        changed = admin_client.patch("/auth/api/profile", json={"display_name": "New Admin"}, headers=write_headers(admin_csrf))
        assert changed.status_code == 200

        listed = owner_client.get("/auth/api/users")
        admin_record = next(user for user in listed.json()["users"] if user["username"] == "admin")
        demoted = owner_client.patch(f"/auth/api/users/{admin_record['user_id']}", json={"role": "user"}, headers=write_headers(owner_csrf))
        assert demoted.status_code == 200
        assert admin_client.get("/auth/session").json()["authenticated"] is False
        assert admin_client.get("/auth/api/users").status_code == 401
        assert auth.users is users
