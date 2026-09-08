"""Behavior-first tests; accounts and all state are synthetic."""
import hashlib
import importlib
import os
import stat
from concurrent.futures import ThreadPoolExecutor

import pytest

import chatlogin as cl


def people():
    return cl.Principal("u1", "One"), cl.Principal("u2", "Two"), cl.Principal("a1", "Admin", cl.Role.ADMIN)


def test_identity_roles_and_owner_do_not_grant_admin_bypass():
    user, other, admin = people()
    guest = cl.Principal.guest()
    assert guest.role == cl.Role.GUEST and not guest.authenticated
    for principal in (user, other, admin):
        assert cl.require_user(principal) == principal
        assert cl.require_owner(principal, principal.user_id) == principal
    with pytest.raises(cl.AccessDenied) as err:
        cl.require_user(guest)
    assert err.value.status_code == 401
    for principal in (user, admin):
        with pytest.raises(cl.AccessDenied) as err:
            cl.require_owner(principal, other.user_id)
        assert err.value.status_code == 403
    with pytest.raises(cl.AccessDenied):
        cl.require_role(user, cl.Role.ADMIN)
    assert cl.require_role(admin, cl.Role.ADMIN) == admin
    with pytest.raises(ValueError):
        cl.Principal(None, "Forged", cl.Role.ADMIN)
    with pytest.raises(ValueError):
        cl.Principal("u1", "Forged", cl.Role.GUEST)
    with pytest.raises(ValueError):
        cl.Principal("u1", "Forged", "superuser")


def test_fixed_multi_and_callback_authentication():
    user, other, _ = people()
    password = cl.hash_password("synthetic-only-pass")
    assert "synthetic-only-pass" not in repr(password)
    fixed = cl.PasswordBackend({"one": (user, password)})
    assert fixed.authenticate("one", "synthetic-only-pass") == user
    assert fixed.authenticate("one", "wrong") is None
    assert fixed.authenticate("unknown", "synthetic-only-pass") is None
    multi = cl.PasswordBackend({"one": (user, password), "two": (other, password)})
    assert multi.authenticate("two", "synthetic-only-pass") == other
    backend = cl.CallbackBackend(lambda u, p: other if (u, p) == ("legacy", "host-password") else None)
    assert backend.authenticate("legacy", "host-password") == other
    assert backend.authenticate("legacy", "wrong") is None
    with pytest.raises(ValueError):
        cl.PasswordBackend({})
    with pytest.raises(ValueError):
        cl.CallbackBackend(lambda u, p: cl.Principal.guest()).authenticate("u", "p")


def test_legacy_pbkdf2_blob_material_and_input_limits():
    salt = b"synthetic-salt-16"
    digest = hashlib.pbkdf2_hmac("sha256", b"host-password", salt, 310000)
    assert cl.verify_pbkdf2("host-password", salt, digest, iterations=310000)
    assert not cl.verify_pbkdf2("wrong", salt, digest, iterations=310000)
    assert not cl.verify_pbkdf2("x" * 1025, salt, digest, iterations=310000)
    with pytest.raises(ValueError):
        cl.hash_password("x" * 1025)
    with pytest.raises(ValueError):
        cl.hash_password("")


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
def test_session_lifecycle_digest_storage_isolation_and_csrf(tmp_path, storage):
    now = [100.0]
    store = cl.MemorySessionStore(max_sessions=10) if storage == "memory" else cl.SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    sessions = cl.SessionManager(store, instance="alpha", ttl=10, clock=lambda: now[0])
    other = cl.SessionManager(store, instance="beta", ttl=10, clock=lambda: now[0])
    user, _, _ = people()
    first = sessions.issue(user)
    assert len(first.token) >= 43 and first.token != first.session.csrf_token
    assert first.token not in repr(first)
    assert sessions.resolve(first.token).principal == user
    if storage == "sqlite":
        data = (tmp_path / "sessions.sqlite3").read_bytes()
        assert first.token.encode() not in data
        assert hashlib.sha256(first.token.encode()).hexdigest().encode() in data
    assert other.resolve(first.token) is None
    cl.require_csrf(first.session, first.session.csrf_token)
    for bad in (None, "", "wrong", "x" * 1025):
        with pytest.raises(cl.AccessDenied) as err:
            cl.require_csrf(first.session, bad)
        assert err.value.status_code == 403
    rotated = sessions.issue(user, previous_token=first.token)
    assert rotated.token != first.token
    assert sessions.resolve(first.token) is None
    assert sessions.resolve(rotated.token) is not None
    # Rotation replaces one bounded session instead of growing past the limit.
    if storage == "memory":
        bounded = cl.SessionManager(cl.MemorySessionStore(max_sessions=2), instance="bound", clock=lambda: now[0])
    else:
        bounded = cl.SessionManager(cl.SQLiteSessionStore(tmp_path / "bounded.sqlite3", max_sessions=2), instance="bound", clock=lambda: now[0])
    first_bounded = bounded.issue(user)
    bounded.issue(user)
    bounded.issue(user, previous_token=first_bounded.token)
    with pytest.raises(cl.StoreFull):
        bounded.issue(user)
    sessions.revoke(rotated.token)
    assert sessions.resolve(rotated.token) is None
    expired = sessions.issue(user)
    now[0] = 110
    assert sessions.resolve(expired.token) is None
    assert sessions.resolve("bad") is None
    if storage == "sqlite":
        assert first.token.encode() not in (tmp_path / "sessions.sqlite3").read_bytes()
        assert stat.S_IMODE((tmp_path / "sessions.sqlite3").stat().st_mode) == 0o600


def test_sqlite_survives_reopening_and_does_not_chmod_shared_parent(tmp_path):
    tmp_path.chmod(0o755)
    db = tmp_path / "private" / "sessions.sqlite3"
    user, _, _ = people()
    manager = cl.SessionManager(cl.SQLiteSessionStore(db), instance="alpha")
    issued = manager.issue(user)
    reopened = cl.SessionManager(cl.SQLiteSessionStore(db), instance="alpha")
    assert reopened.resolve(issued.token).principal == user
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700


def test_memory_is_bounded_and_thread_safe():
    user, _, _ = people()
    sessions = cl.SessionManager(cl.MemorySessionStore(max_sessions=4), instance="alpha")
    def attempt(_):
        try:
            return sessions.issue(user)
        except cl.StoreFull:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert len([r for r in results if r is not None]) == 4


def test_paths_are_explicit_isolated_and_side_effect_free(tmp_path, monkeypatch):
    home = tmp_path / "chatarch"
    monkeypatch.setenv("CHATARCH_HOME", str(home))
    a = cl.state_paths("alpha")
    b = cl.state_paths("beta")
    assert a.database == home / "chatlogin" / "instances" / "alpha" / "sessions.sqlite3"
    assert a.database != b.database
    assert not home.exists()
    importlib.reload(cl)
    assert not home.exists()
    for bad in ("", "..", "../bad", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            cl.state_paths(bad)


@pytest.mark.parametrize("value", ["//evil.test", "https://evil.test", "/\\evil.test", "/%2fevil.test", "/%252fevil.test", " /local", "/\nevil", "/%0d%0aLocation:evil", "javascript:alert(1)", "///evil", "/%5cevil.test"])
def test_next_rejects_malicious_paths(value):
    assert cl.safe_next(value) == "/"


@pytest.mark.parametrize("value", ["/", "/meetings", "/home?a=1#ok", "/中文"])
def test_next_accepts_local_paths(value):
    assert cl.safe_next(value) == value


def test_rate_limit_bounded_concurrent_and_expires():
    now = [0.0]
    limiter = cl.LoginRateLimiter(limit=3, window=60, max_keys=2, clock=lambda: now[0])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: limiter.allow("client-1"), range(12)))
    assert sum(results) == 3
    assert limiter.allow("client-2")
    assert not limiter.allow("client-3")
    now[0] = 60
    assert limiter.allow("client-3")
