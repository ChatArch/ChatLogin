"""Core fail-closed contracts using synthetic state only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import stat
from types import SimpleNamespace

import pytest
import chatlogin as cl


@pytest.mark.parametrize("expiry", [float("nan"), float("inf"), -float("inf"), True, "123", None])
def test_session_rejects_invalid_expiry(expiry):
    with pytest.raises(ValueError):
        cl.Session(cl.Principal("u"), expiry, "x" * 43)


@pytest.mark.parametrize("principal", [None, cl.Principal.guest(), SimpleNamespace(authenticated=True)])
def test_session_requires_authenticated_principal(principal):
    with pytest.raises(ValueError):
        cl.Session(principal, 100, "x" * 43)


def test_require_user_rejects_duck_identity():
    with pytest.raises(cl.AccessDenied):
        cl.require_user(SimpleNamespace(authenticated=True))


@pytest.mark.parametrize("csrf", [None, "", "x" * 15, "x" * 1025, "x" * 32 + "\ud800", "x" * 32 + "\n"])
def test_session_rejects_invalid_csrf(csrf):
    with pytest.raises(ValueError):
        cl.Session(cl.Principal("u"), 100, csrf)


@pytest.mark.parametrize("fields", [
    {"salt": "x" * 16}, {"salt": b"short"}, {"salt": b"x" * 1025},
    {"digest": "x" * 32}, {"digest": b"short"},
    {"iterations": True}, {"iterations": 0}, {"iterations": 1.5},
    {"iterations": float("nan")}, {"iterations": 10_000_001},
])
def test_password_hash_validates_configuration(fields):
    kwargs = dict(salt=b"x" * 16, digest=b"x" * 32)
    kwargs.update(fields)
    with pytest.raises(ValueError):
        cl.PasswordHash(**kwargs)


def test_password_backend_cannot_configure_none_identity():
    with pytest.raises(ValueError):
        cl.PasswordBackend({"u": (None, cl.PasswordHash(b"x" * 16, b"x" * 32))})


def test_hash_defaults_and_legacy_blob_verifier():
    assert cl.hash_password("synthetic").iterations == 600_000
    salt = b"legacy-salt-12345"
    digest = hashlib.pbkdf2_hmac("sha256", b"synthetic", salt, 310_000)
    assert cl.verify_pbkdf2("synthetic", salt, digest)


def test_digest_rejects_invalid_utf8_instead_of_aliasing_replacement():
    assert cl.SessionManager.digest("x" * 32 + "\ud800") is None
    assert cl.SessionManager.digest("x" * 32 + "?") is not None


@pytest.mark.parametrize("mode", [0o644, 0o620, 0o604, 0o602, 0o660])
def test_sqlite_refuses_shared_file_without_chmod_or_write(tmp_path, mode):
    db = tmp_path / "existing.sqlite3"
    db.write_bytes(b"not a database")
    db.chmod(mode)
    parent_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    with pytest.raises(ValueError):
        cl.SQLiteSessionStore(db)
    assert db.read_bytes() == b"not a database"
    assert stat.S_IMODE(db.stat().st_mode) == mode
    assert stat.S_IMODE(tmp_path.stat().st_mode) == parent_mode


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return cl.MemorySessionStore(max_sessions=2)
    return cl.SQLiteSessionStore(tmp_path / "private" / "sessions.sqlite3", max_sessions=2)


def test_capacity_is_global_and_operations_remain_namespaced(store):
    a = cl.SessionManager(store, instance="a", clock=lambda: 100)
    b = cl.SessionManager(store, instance="b", clock=lambda: 100)
    first = a.issue(cl.Principal("a"))
    second = b.issue(cl.Principal("b"))
    with pytest.raises(cl.StoreFull):
        b.issue(cl.Principal("b"), previous_token=first.token)
    assert b.resolve(first.token) is None
    b.revoke(first.token)
    store.purge_expired("b", 1e10)
    assert a.resolve(first.token) is not None
    assert b.resolve(second.token) is None


def test_failed_replacement_preserves_old_session(store):
    session = cl.Session(cl.Principal("u"), 1000, "x" * 43)
    store.put("a", "1" * 64, session)
    store.put("a", "2" * 64, session)
    with pytest.raises(ValueError):
        store.put("a", "2" * 64, session, previous_digest="1" * 64)
    assert store.get("a", "1" * 64) == session
    assert store.get("a", "2" * 64) == session


def test_rotation_at_capacity_has_one_winner(store):
    a = cl.SessionManager(store, instance="a", clock=lambda: 100)
    first = a.issue(cl.Principal("u"))
    a.issue(cl.Principal("other"))
    # SQLite workers also exercise independent connections/store objects.
    def rotate(_):
        worker_store = (cl.SQLiteSessionStore(store.database, max_sessions=2)
                        if isinstance(store, cl.SQLiteSessionStore) else store)
        worker = cl.SessionManager(worker_store, instance="a", clock=lambda: 100)
        try:
            return worker.issue(cl.Principal("u"), previous_token=first.token)
        except cl.StoreFull:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        winners = [result for result in pool.map(rotate, range(8)) if result]
    assert len(winners) == 1
    assert a.resolve(first.token) is None
    assert a.resolve(winners[0].token) is not None


@pytest.mark.parametrize("store_cls", [cl.MemorySessionStore, cl.SQLiteSessionStore])
@pytest.mark.parametrize("bound", [True, 1.5, float("nan"), "2", 0])
def test_store_capacity_requires_positive_integer(store_cls, bound, tmp_path):
    with pytest.raises(ValueError):
        if store_cls is cl.SQLiteSessionStore:
            store_cls(tmp_path / "must-not-exist" / "sessions.sqlite3", max_sessions=bound)
        else:
            store_cls(max_sessions=bound)
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 1.5}, {"limit": "2"},
    {"max_keys": float("nan")}, {"max_keys": True}, {"window": True},
    {"window": "60"}, {"window": float("inf")}])
def test_limiter_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        cl.LoginRateLimiter(**kwargs)


@pytest.mark.parametrize("key", [None, 1, [], "", "x" * 1025, "界" * 400, "x\ud800"])
def test_limiter_invalid_key_does_not_purge_live_state(key):
    now = [0]
    limiter = cl.LoginRateLimiter(limit=1, clock=lambda: now[0])
    assert limiter.allow("valid")
    now[0] = 100
    with pytest.raises(ValueError):
        limiter.allow(key)
    now[0] = 0
    assert not limiter.allow("valid")


@pytest.mark.parametrize("now", [float("nan"), float("inf"), True, "1"])
def test_limiter_invalid_clock_does_not_write(now):
    clock = [0]
    limiter = cl.LoginRateLimiter(limit=1, clock=lambda: clock[0])
    assert limiter.allow("valid")
    clock[0] = now
    with pytest.raises(ValueError):
        limiter.allow("other")
    clock[0] = 0
    assert not limiter.allow("valid")


def test_invalid_session_replacement_keeps_original(store):
    session = cl.Session(cl.Principal("u"), 1000, "x" * 43)
    store.put("a", "1" * 64, session)
    with pytest.raises(ValueError):
        store.put("a", "2" * 64, None, previous_digest="1" * 64)
    assert store.get("a", "1" * 64) == session
    assert store.get("a", "2" * 64) is None


@pytest.mark.parametrize("ttl", [True, "60", None])
def test_manager_rejects_non_numeric_ttl(ttl):
    with pytest.raises(ValueError):
        cl.SessionManager(cl.MemorySessionStore(), instance="a", ttl=ttl)


@pytest.mark.parametrize("bad_clock", [float("nan"), float("inf"), True, "1"])
def test_manager_invalid_clock_cannot_resolve_or_replace(bad_clock):
    now = [100]
    manager = cl.SessionManager(cl.MemorySessionStore(max_sessions=1), instance="a", clock=lambda: now[0])
    first = manager.issue(cl.Principal("u"))
    now[0] = bad_clock
    with pytest.raises(ValueError):
        manager.resolve(first.token)
    with pytest.raises(ValueError):
        manager.issue(cl.Principal("u"), previous_token=first.token)
    now[0] = 100
    assert manager.resolve(first.token) is not None


def test_legacy_verifier_rejects_bool_iterations():
    with pytest.raises(ValueError):
        cl.verify_pbkdf2("synthetic", b"x" * 16, b"x" * 32, iterations=True)
