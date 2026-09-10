"""Real loopback login-service acceptance, also run against the built wheel."""
from contextlib import contextmanager
import socket
import threading
import time

import httpx
from fastapi import Depends, FastAPI
import uvicorn

from chatlogin import MemorySessionStore, PasswordBackend, Principal, SessionManager, hash_password
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI


@contextmanager
def login_service():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    backend = PasswordBackend({"test-user": (Principal("test-user", "Test user"), hash_password("synthetic-test-password"))})
    auth = FastAPIAuth(backend, SessionManager(MemorySessionStore(max_sessions=8), instance="tcp-smoke", ttl=60),
                      origin=origin, prefix="/auth", cookie=CookieSettings(secure=False, max_age=60),
                      ui=LoginUI(title="Local login service", layout="split", appearance="light"))
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/private")
    def private(principal=Depends(auth.current_user)):
        return {"user_id": principal.user_id}

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=sock.getsockname()[1],
                           access_log=False, log_level="warning", lifespan="off", timeout_graceful_shutdown=5))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        with httpx.Client(base_url=origin, trust_env=False, timeout=3) as client:
            deadline = time.monotonic() + 10
            while True:
                try:
                    response = client.get("/auth/session")
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Owned login service did not become ready")
                time.sleep(0.02)
            yield client, origin
    finally:
        server.should_exit = True
        thread.join(timeout=8)
        sock.close()
        assert not thread.is_alive(), "Owned login service did not close gracefully"


def test_real_tcp_login_service():
    with login_service() as (client, origin):
        assert client.get("/private").status_code == 401
        page = client.get("/auth/?next=/private")
        assert page.status_code == 200
        assert 'class="chatlogin__form"' in page.text
        assert 'data-layout="split"' in page.text
        for name, media in [("login.css", "text/css"), ("login.js", "javascript")]:
            asset = client.get("/auth/assets/" + name)
            assert asset.status_code == 200 and media in asset.headers["content-type"]
        body = {"username": "test-user", "password": "synthetic-test-password", "next": "/private"}
        assert client.post("/auth/login", json=body, headers={"Origin": "https://wrong.invalid"}).status_code == 403
        assert client.post("/auth/login", json={**body, "password": "wrong"}, headers={"Origin": origin}).status_code == 401
        login = client.post("/auth/login", json=body, headers={"Origin": origin})
        assert login.status_code == 200 and login.json()["next"] == "/private"
        assert "HttpOnly" in login.headers["set-cookie"]
        token = client.cookies.get("chatlogin_session")
        assert token
        session = client.get("/auth/session").json()
        assert session["authenticated"] and session["user"]["user_id"] == "test-user"
        assert client.get("/private").json() == {"user_id": "test-user"}
        assert client.post("/auth/logout", headers={"Origin": origin}).status_code == 403
        assert client.post("/auth/logout", headers={"Origin": origin, "X-CSRF-Token": session["csrf_token"]}).status_code == 200
        assert not client.get("/auth/session").json()["authenticated"]
        client.cookies.set("chatlogin_session", token)
        assert client.get("/private").status_code == 401
