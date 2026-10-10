"""Real provider integration contracts, not duplicate credential fixtures."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chatlogin import ManagedUsers
from chatlogin.managed_web import ManagedAuth, create_managed_auth


def test_factory_accepts_existing_real_managed_service_without_new_home(tmp_path):
    users = ManagedUsers.in_memory("shared-users")
    try:
        users.bootstrap_owner("owner", "owner-password")
        auth = create_managed_auth("shared-users", origin="https://managed.example.com", users=users)
        assert auth.users is users
        assert users.store.database is None
    finally:
        users.close()


def test_default_managed_cookies_are_session_namespace_scoped():
    a = ManagedUsers.in_memory("alpha")
    b = ManagedUsers.in_memory("bravo")
    try:
        auth_a = ManagedAuth(a, origin="https://managed.example.com", prefix="/a/auth")
        auth_b = ManagedAuth(b, origin="https://managed.example.com", prefix="/b/auth")
        assert auth_a.cookie.name != auth_b.cookie.name
    finally:
        a.close()
        b.close()


def test_managed_demo_supports_explicit_loopback_http_without_persistent_state():
    from chatlogin.managed_demo import create_managed_demo_app
    with TestClient(create_managed_demo_app(origin="http://127.0.0.1:8765"), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/health").json()["synthetic"] is True
        fixtures = client.get("/api/managed-demo/accounts").json()["accounts"]
        owner = next(r for r in fixtures if r["role"] == "owner")
        login = client.post("/auth/login", json={"username": owner["username"], "password": owner["password"]}, headers={"Origin":"http://127.0.0.1:8765"})
        assert login.status_code == 200
        assert client.get("/auth/users").status_code == 200
