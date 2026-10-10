from fastapi import FastAPI
from fastapi.testclient import TestClient
from chatlogin import ManagedUsers
from chatlogin.managed_web import ManagedAuth


def test_json_only_plugin_preserves_api_without_default_pages_or_assets():
    users = ManagedUsers.in_memory("headless-plugin")
    try:
        users.bootstrap_owner("owner", "owner-password")
        auth = ManagedAuth(users, origin="https://plugin.example.com", pages=False)
        app = FastAPI()
        app.include_router(auth.router)
        with TestClient(app, base_url="https://plugin.example.com") as client:
            for path in ("/auth/", "/auth/users", "/auth/profile", "/auth/assets/users.js", "/auth/assets/login.css"):
                assert client.get(path).status_code == 404
            assert client.get("/auth/session").json()["authenticated"] is False
            response = client.post("/auth/login", json={"username":"owner", "password":"owner-password"}, headers={"Origin":"https://plugin.example.com"})
            assert response.status_code == 200
            assert client.get("/auth/api/users").status_code == 200
    finally:
        users.close()
