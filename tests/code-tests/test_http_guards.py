"""Negative HTTP boundary regressions; no network or production credentials."""
import asyncio
import inspect
import json
import threading

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import httpx

import chatlogin as cl
from chatlogin.fastapi import CookieSettings, FastAPIAuth

ORIGIN = "https://example.test"
BODY = {"username": "one", "password": "test-password"}


def application(**kwargs):
    backend = kwargs.pop("backend", cl.CallbackBackend(lambda u, p: cl.Principal("u1", "Synthetic")))
    sessions = kwargs.pop("sessions", cl.SessionManager(cl.MemorySessionStore(), instance="guards"))
    auth = FastAPIAuth(backend, sessions, origin=ORIGIN, **kwargs)
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/private")
    async def private(user=Depends(auth.current_user)):
        return user.as_dict()

    @app.post("/write")
    async def write(user=Depends(auth.csrf_user)):
        return user.as_dict()

    return auth, app, TestClient(app, base_url=ORIGIN)


def login(client, **kwargs):
    return client.post("/auth/login", json=BODY, headers={"Origin": ORIGIN}, **kwargs)


def test_stream_stops_at_first_overflow_without_draining():
    auth, _, _ = application(max_body_bytes=128)
    reads = []

    async def receive():
        reads.append(1)
        return {"type": "http.request", "body": b"x" * 80, "more_body": len(reads) < 4}

    request = Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth._json_body(request))
    assert exc.value.status_code == 413
    assert len(reads) == 2


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"])
def test_non_json_login_is_rejected(content_type):
    _, _, client = application()
    headers = {"Origin": ORIGIN}
    if content_type:
        headers["Content-Type"] = content_type
    response = client.post("/auth/login", content=json.dumps(BODY), headers=headers)
    assert response.status_code == 415
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("raw", [
    '{"username":"one","password":"test-password","next":[]}',
    '{"username":"one","password":"test-password","next":NaN}',
    '{"username":"other","username":"one","password":"test-password"}',
])
def test_malformed_json_shape_is_rejected(raw):
    _, _, client = application()
    response = client.post("/auth/login", content=raw, headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"


def test_default_limiter_is_bounded_and_per_instance():
    first, _, _ = application()
    second, _, _ = application()
    assert isinstance(first.limiter, cl.LoginRateLimiter)
    assert first.limiter is not second.limiter
    assert first.limiter.limit > 0 and first.limiter.max_keys > 0


def test_limiter_cannot_be_bypassed_by_username_or_forwarded_ip():
    limiter = cl.LoginRateLimiter(limit=1)
    auth, _, client = application(limiter=limiter, backend=cl.CallbackBackend(lambda u, p: None))
    assert auth.limiter is limiter
    first = client.post("/auth/login", json=BODY, headers={"Origin": ORIGIN, "X-Forwarded-For": "192.0.2.1"})
    second = client.post("/auth/login", json={**BODY, "username": "two"}, headers={"Origin": ORIGIN, "X-Forwarded-For": "192.0.2.2"})
    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/auth/session", "/private"])
def test_host_guard_covers_session_reads_before_resolving(path):
    auth, _, client = application()
    calls = []
    auth.sessions.resolve = lambda token: calls.append(token)
    response = client.get(path, headers={"Host": "evil.test", "X-Forwarded-Host": "example.test"})
    assert response.status_code == 400
    assert calls == []
    assert response.headers["cache-control"] == "no-store"


def test_native_cookie_rotation_still_requires_origin():
    _, _, client = application(allow_native=True)
    first = client.post("/auth/login", json=BODY, headers={"X-ChatLogin-Client": "native"})
    assert first.status_code == 200
    second = client.post("/auth/login", json=BODY, headers={"X-ChatLogin-Client": "native", "X-CSRF-Token": first.json()["csrf_token"]})
    assert second.status_code == 403
    assert "set-cookie" not in second.headers


def test_native_bypass_rejects_browser_fetch_metadata():
    _, _, client = application(allow_native=True)
    result = client.post("/auth/login", json=BODY, headers={"X-ChatLogin-Client": "native", "Sec-Fetch-Site": "cross-site"})
    assert result.status_code == 403


def test_cookie_deletion_matches_issuance_attributes():
    _, _, client = application(cookie=CookieSettings(same_site="strict", path="/auth"))
    first = login(client)
    result = client.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrf_token"]})
    assert result.status_code == 200
    for attribute in ("Secure", "HttpOnly", "SameSite=strict", "Path=/auth", "Max-Age=0"):
        assert attribute in result.headers["set-cookie"]


@pytest.mark.parametrize("origin", ["https://good.test\n", "https://good.test:bad", "https://good.test:99999", "https://good.test:", "https://good.test\\evil", "https://bad host", "https://good.test?", "https://good.test#"])
def test_invalid_origins_fail_at_construction(origin):
    with pytest.raises(ValueError):
        FastAPIAuth(cl.CallbackBackend(lambda u, p: None), cl.SessionManager(cl.MemorySessionStore(), instance="config"), origin=origin)


@pytest.mark.parametrize("prefix", ["auth", "//evil", "/auth?x", "/auth#x", "/auth\\x", "/auth/{name}", "/auth/../x", "/auth\n"])
def test_invalid_prefixes_fail_at_construction(prefix):
    with pytest.raises(ValueError):
        application(prefix=prefix)


@pytest.mark.parametrize("settings", [{"path": "/; Secure"}, {"path": "/;x"}, {"path": "//evil"}, {"path": "/x\\y"}, {"path": "/x\x7f"}, {"name": "__Secure-demo", "secure": False}, {"max_age": True}, {"http_only": "false"}])
def test_invalid_cookie_configuration_fails_early(settings):
    with pytest.raises(ValueError):
        CookieSettings(**settings)


@pytest.mark.parametrize("operation", ["authenticate", "resolve", "issue", "revoke"])
def test_backend_errors_are_safe_no_store(operation):
    auth, _, client = application()
    first = login(client) if operation == "revoke" else None

    def broken(*args, **kwargs):
        raise HTTPException(418, detail="synthetic backend secret", headers={"X-Leak": "session"})

    target = auth.backend if operation == "authenticate" else auth.sessions
    setattr(target, operation, broken)
    if operation == "revoke":
        response = client.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrf_token"]})
    elif operation == "resolve":
        response = client.get("/auth/session")
    else:
        response = login(client)
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.text and "x-leak" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("persistent", [False, True])
def test_all_sync_auth_and_session_calls_leave_event_loop(tmp_path, persistent):
    options = {}
    if persistent:
        options = {
            "backend": cl.PasswordBackend({"one": (cl.Principal("u1", "Synthetic"), cl.hash_password(BODY["password"]))}),
            "sessions": cl.SessionManager(cl.SQLiteSessionStore(tmp_path / "sessions.sqlite3"), instance="guards"),
        }

    async def scenario():
        auth, app, _ = application(**options)
        loop_thread = threading.get_ident()
        calls = []
        for owner, method in [(auth.backend, "authenticate"), (auth.sessions, "resolve"), (auth.sessions, "issue"), (auth.sessions, "revoke")]:
            original = getattr(owner, method)

            def checked(*args, _original=original, _method=method, **kwargs):
                calls.append((_method, threading.get_ident() != loop_thread))
                return _original(*args, **kwargs)

            setattr(owner, method, checked)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            first = await client.post("/auth/login", json=BODY, headers={"Origin": ORIGIN})
            assert first.status_code == 200
            headers = {"Origin": ORIGIN, "X-CSRF-Token": first.json()["csrf_token"]}
            assert (await client.get("/auth/session")).status_code == 200
            assert (await client.get("/private")).status_code == 200
            assert (await client.post("/write", headers=headers)).status_code == 200
            assert (await client.post("/auth/logout", headers=headers)).status_code == 200
        assert {name for name, _ in calls} == {"authenticate", "resolve", "issue", "revoke"}
        assert all(off_loop for _, off_loop in calls), calls
        assert inspect.iscoroutinefunction(auth.current_user)
        assert inspect.iscoroutinefunction(auth.csrf_user)
    asyncio.run(scenario())


@pytest.mark.parametrize("settings", [{"allow_native": "false"}, {"allow_native": 1}, {"cookie": {"secure": False}}])
def test_security_options_are_explicit_types(settings):
    with pytest.raises(ValueError):
        application(**settings)


@pytest.mark.parametrize("field", ["username", "password", "next"])
def test_json_surrogates_are_rejected_before_backend(field):
    _, _, client = application()
    response = client.post("/auth/login", content=json.dumps({**BODY, field: "\ud800"}),
                           headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"


def test_default_limiter_enforces_attempts_without_cookie():
    auth, _, client = application(backend=cl.CallbackBackend(lambda u, p: None))
    for attempt in range(auth.limiter.limit):
        result = client.post("/auth/login", json={**BODY, "username": f"user{attempt}"}, headers={"Origin": ORIGIN})
        assert result.status_code == 401
    assert login(client).status_code == 429


@pytest.mark.parametrize("origin", ["http://localhost:8000", "https://example.test", "http://[::1]:8000"])
def test_concrete_origins_and_canonical_host_are_accepted(origin):
    auth = FastAPIAuth(cl.CallbackBackend(lambda u, p: None), cl.SessionManager(cl.MemorySessionStore(), instance="valid"), origin=origin)
    app = FastAPI()
    app.include_router(auth.router)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin) as client:
            assert (await client.get("/auth/session")).status_code == 200
    asyncio.run(scenario())
