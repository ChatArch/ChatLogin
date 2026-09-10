"""Offline compatibility contract for the built-in ChatVoice schema backend."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from chatlogin import AccessDenied, CallbackBackend, Principal, Role, Session, SessionManager, StoreFull

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
PASSWORD = "synthetic-test-password"
OLD_TOKEN = "synthetic-legacy-session-token"
OLD_DIGEST = hashlib.sha256(OLD_TOKEN.encode()).hexdigest()
OLD_CSRF = "c" * 32
SCHEMA = """
CREATE TABLE accounts (id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE,
 display_name TEXT NOT NULL, password_salt BLOB NOT NULL,
 password_hash BLOB NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE auth_sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
 csrf_token TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 FOREIGN KEY (user_id) REFERENCES accounts(id) ON DELETE CASCADE);
"""


def test_public_backend_available():
    assert importlib.util.find_spec("chatlogin.backends") is not None, "Missing built-in optional backends"
    module = importlib.import_module("chatlogin.backends.chatvoice")
    exports = importlib.import_module("chatlogin.backends")
    assert exports.ChatVoiceAuth is module.ChatVoiceAuth
    assert exports.ChatVoiceSessionStore is module.ChatVoiceSessionStore


@pytest.fixture
def module():
    return importlib.import_module("chatlogin.backends.chatvoice")


@pytest.fixture
def host(tmp_path):
    class Host:
        def __init__(self):
            self.path = tmp_path / "legacy.sqlite3"
            self.now = NOW.timestamp()
            self.mutex = threading.Lock()
            self.active = False
            self.lock_entries = 0

        @contextmanager
        def lock(self):
            assert not self.active, "Store must not nest the host lock"
            with self.mutex:
                self.active = True
                self.lock_entries += 1
                try:
                    yield
                finally:
                    self.active = False

        def connect(self):
            assert self.active, "Connection must be opened under the current host lock"
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            return db

        def clock(self):
            return self.now

        def seed(self):
            with sqlite3.connect(self.path) as db:
                db.executescript(SCHEMA)
                for name in ("alice", "bob"):
                    salt = name.encode().ljust(16, b"x")
                    digest = hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), salt, 310_000)
                    db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)",
                               ("usr_" + name, name + "@example.invalid", name.title(), salt, digest, NOW.isoformat()))
                db.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?)",
                           (OLD_DIGEST, "usr_alice", OLD_CSRF, NOW.isoformat(),
                            (NOW + timedelta(days=30)).isoformat()))

        def query(self, sql, args=()):
            with self.lock(), closing(self.connect()) as db, db:
                return [tuple(row) for row in db.execute(sql, args)]

    result = Host()
    result.seed()
    return result


@pytest.fixture
def auth(host, module):
    return module.ChatVoiceAuth(lambda: host.connect(), lambda: host.lock(), lambda: host.clock(), ttl=3600)


def test_real_login_uses_old_password_material_and_digest_only_storage(host, auth):
    schema = host.query("SELECT name, sql FROM sqlite_master ORDER BY name")
    accounts = host.query("SELECT * FROM accounts ORDER BY id")
    assert isinstance(auth.backend, CallbackBackend)
    assert isinstance(auth.manager, SessionManager)
    assert auth.manager.store is auth.store
    assert auth.store.max_sessions == 10_000
    issued = auth.login("alice@example.invalid", PASSWORD)
    assert issued.session.principal == Principal("usr_alice", "Alice", Role.USER)
    row = auth.resolve_row(issued.token)
    assert row["user_id"] == "usr_alice"
    assert row["account"] == "alice@example.invalid"
    assert row["_chatlogin_session"] == issued.session
    stored = host.query("SELECT token_hash, csrf_token, created_at, expires_at FROM auth_sessions WHERE token_hash = ?",
                        (hashlib.sha256(issued.token.encode()).hexdigest(),))[0]
    assert stored[0] != issued.token
    assert stored[1] == issued.session.csrf_token
    assert datetime.fromisoformat(stored[2]).timestamp() == host.now
    assert datetime.fromisoformat(stored[3]).timestamp() == host.now + 3600
    assert host.query("SELECT * FROM accounts ORDER BY id") == accounts
    assert host.query("SELECT name, sql FROM sqlite_master ORDER BY name") == schema


@pytest.mark.parametrize("account,password", [
    ("alice@example.invalid", "wrong"), ("missing@example.invalid", PASSWORD),
    ("", PASSWORD), (None, PASSWORD), ("alice@example.invalid", None),
    ("alice@example.invalid", ""), ("alice@example.invalid", "x" * 1025),
    ("ALICE@EXAMPLE.INVALID", PASSWORD), (" alice@example.invalid ", PASSWORD),
])
def test_bad_credentials_never_create_identity_or_session(host, auth, account, password):
    before = host.query("SELECT * FROM auth_sessions")
    assert auth.login(account, password) is None
    assert host.query("SELECT * FROM auth_sessions") == before
    assert len(host.query("SELECT * FROM accounts")) == 2


def test_missing_user_still_pays_legacy_pbkdf2_cost(host, auth, module, monkeypatch):
    actual = module.verify_pbkdf2
    iterations = []

    def verify(*args, **kwargs):
        iterations.append(kwargs["iterations"])
        return actual(*args, **kwargs)

    monkeypatch.setattr(module, "verify_pbkdf2", verify)
    assert auth.login("alice@example.invalid", "wrong") is None
    assert auth.login("missing@example.invalid", "wrong") is None
    assert iterations == [310_000, 310_000]


@pytest.mark.parametrize("token", [None, "", "short", "x" * 1025, "unknown-opaque-token"])
def test_anonymous_resolve_and_logout_do_not_create_rows(host, auth, token):
    before = host.query("SELECT * FROM auth_sessions")
    assert auth.resolve_row(token) is None
    auth.logout(token)
    assert host.query("SELECT * FROM auth_sessions") == before


def test_legacy_session_live_account_join_and_logout(host, auth):
    row = auth.resolve_row(OLD_TOKEN)
    assert row["csrf_token"] == OLD_CSRF
    assert row["_chatlogin_session"].principal.role is Role.USER
    host.query("UPDATE accounts SET display_name = 'Updated' WHERE id = 'usr_alice'")
    assert auth.resolve_row(OLD_TOKEN)["display_name"] == "Updated"
    assert auth.resolve_row(OLD_TOKEN)["_chatlogin_session"].principal.display_name == "Updated"
    auth.logout(OLD_TOKEN)
    assert auth.resolve_row(OLD_TOKEN) is None
    assert host.query("SELECT * FROM auth_sessions") == []


def test_deleted_account_cannot_resolve(host, auth):
    host.query("DELETE FROM accounts WHERE id = 'usr_alice'")
    assert auth.resolve_row(OLD_TOKEN) is None


def test_expiry_boundary_and_dynamic_clock(host, auth):
    issued = auth.login("bob@example.invalid", PASSWORD)
    host.now = issued.session.expires_at - 1
    assert auth.resolve_row(issued.token) is not None
    host.now += 1
    assert auth.resolve_row(issued.token) is None
    assert host.query("SELECT 1 FROM auth_sessions WHERE token_hash = ?", (auth.manager.digest(issued.token),)) == []


@pytest.mark.parametrize("submitted", [None, "", "wrong", "c" * 31, "c" * 33])
def test_csrf_rejects_mismatch(auth, submitted):
    row = auth.resolve_row(OLD_TOKEN)
    auth.check_csrf(row, OLD_CSRF)
    with pytest.raises(AccessDenied) as exc:
        auth.check_csrf(row, submitted)
    assert exc.value.status_code == 403


def test_new_session_csrf(auth):
    issued = auth.login("alice@example.invalid", PASSWORD)
    auth.check_csrf(auth.resolve_row(issued.token), issued.session.csrf_token)


@pytest.mark.parametrize("field,value", [("expires_at", "invalid"), ("csrf_token", "bad")])
def test_corrupt_session_fails_closed_and_is_removed(host, auth, field, value):
    host.query(f"UPDATE auth_sessions SET {field} = ?", (value,))
    assert auth.resolve_row(OLD_TOKEN) is None
    assert host.query("SELECT * FROM auth_sessions") == []


def test_purge_handles_iso_offsets_and_corrupt_expiry(host, auth):
    # Same instant as NOW, but lexical comparison would misorder this +08:00 value.
    host.query("UPDATE auth_sessions SET expires_at = ?", (NOW.astimezone(timezone(timedelta(hours=8))).isoformat(),))
    auth.store.purge_expired("chatvoice", host.now)
    assert host.query("SELECT * FROM auth_sessions") == []
    issued = auth.login("alice@example.invalid", PASSWORD)
    host.query("UPDATE auth_sessions SET expires_at = 'corrupt'")
    auth.store.purge_expired("chatvoice", host.now)
    assert auth.resolve_row(issued.token) is None


@pytest.mark.parametrize("operation", ["get", "read_row", "put", "delete", "purge_expired"])
def test_every_store_operation_rejects_foreign_namespace(host, auth, operation):
    session = auth.store.get("chatvoice", OLD_DIGEST)
    args = {"get": (OLD_DIGEST,), "read_row": (OLD_DIGEST,), "put": ("a" * 64, session),
            "delete": (OLD_DIGEST,), "purge_expired": (host.now,)}
    before = host.query("SELECT * FROM auth_sessions")
    with pytest.raises(ValueError, match="chatvoice"):
        getattr(auth.store, operation)("other", *args[operation])
    assert host.query("SELECT * FROM auth_sessions") == before


@pytest.mark.parametrize("bad", [None, Principal.guest(), Session(Principal("admin", role=Role.ADMIN), NOW.timestamp() + 60, OLD_CSRF)])
def test_store_rejects_non_user_subjects(host, auth, bad):
    with pytest.raises(ValueError, match="ordinary user"):
        auth.store.put("chatvoice", "a" * 64, bad)
    assert len(host.query("SELECT * FROM auth_sessions")) == 1


def test_capacity_and_atomic_replacement(host, module):
    store = module.ChatVoiceSessionStore(host.connect, host.lock, host.clock, max_sessions=1)
    session = store.get("chatvoice", OLD_DIGEST)
    with pytest.raises(StoreFull):
        store.put("chatvoice", "a" * 64, session)
    with pytest.raises(StoreFull):
        store.put("chatvoice", "a" * 64, session, previous_digest="b" * 64)
    store.put("chatvoice", "a" * 64, session, previous_digest=OLD_DIGEST)
    assert store.get("chatvoice", OLD_DIGEST) is None
    assert store.get("chatvoice", "a" * 64) == session
    with pytest.raises(ValueError, match="already exists"):
        store.put("chatvoice", "a" * 64, session, previous_digest="a" * 64)
    assert store.get("chatvoice", "a" * 64) == session


def test_failed_replacement_rolls_back_old_session(host, auth):
    host.query("CREATE TRIGGER fail_insert BEFORE INSERT ON auth_sessions BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    session = auth.store.get("chatvoice", OLD_DIGEST)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        auth.manager.issue(session.principal, previous_token=OLD_TOKEN)
    assert auth.resolve_row(OLD_TOKEN)["_chatlogin_session"] == session
    assert len(host.query("SELECT * FROM auth_sessions")) == 1


def test_capacity_shared_across_concurrent_store_instances(host, module):
    host.query("DELETE FROM auth_sessions")
    barrier = threading.Barrier(2)
    session = Session(Principal("usr_alice", "Alice"), host.now + 60, OLD_CSRF)

    def writer(digest):
        def connect():
            db = sqlite3.connect(host.path, timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            return db

        mutex = threading.Lock()  # Different host locks: SQLite must serialize writers.
        store = module.ChatVoiceSessionStore(connect, lambda: mutex, host.clock, max_sessions=1)
        barrier.wait(timeout=5)
        try:
            store.put("chatvoice", digest, session)
            return "stored"
        except StoreFull:
            return "full"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ("a" * 64, "b" * 64)))
    assert sorted(results) == ["full", "stored"]
    assert len(host.query("SELECT * FROM auth_sessions")) == 1


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5])
def test_capacity_validation(host, module, capacity):
    with pytest.raises(ValueError, match="max_sessions"):
        module.ChatVoiceSessionStore(host.connect, host.lock, host.clock, max_sessions=capacity)


def test_callbacks_follow_path_lock_and_clock_changes(host, auth, tmp_path):
    issued = auth.login("alice@example.invalid", PASSWORD)
    host.path = tmp_path / "other.sqlite3"
    host.seed()
    host.now += 600
    host.mutex = threading.Lock()
    entries = host.lock_entries
    assert auth.resolve_row(issued.token) is None
    second = auth.login("bob@example.invalid", PASSWORD)
    assert second.session.expires_at == host.now + 3600
    assert host.lock_entries > entries
    created = host.query("SELECT created_at FROM auth_sessions WHERE token_hash = ?", (auth.manager.digest(second.token),))[0][0]
    assert datetime.fromisoformat(created).timestamp() == host.now


def test_import_requires_neither_chatvoice_nor_web_extra():
    code = f"""
import sys
sys.path.insert(0, {str(ROOT / 'src')!r})
class RejectOptional:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'chatvoice', 'fastapi', 'starlette', 'jinja2'}}:
            raise AssertionError('Optional dependency imported: ' + fullname)
sys.meta_path.insert(0, RejectOptional())
from chatlogin.backends import ChatVoiceAuth, ChatVoiceSessionStore
assert ChatVoiceAuth.__module__ == 'chatlogin.backends.chatvoice'
assert not any(name in sys.modules for name in ('chatvoice', 'fastapi', 'starlette', 'jinja2'))
"""
    result = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["default", "override", "headless"])
def test_backend_composes_with_unchanged_fastapi_and_ui(auth, mode):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from chatlogin.fastapi import FastAPIAuth
    from chatlogin.ui import LoginUI

    ui = None if mode == "headless" else LoginUI()
    if mode == "override":
        ui = LoginUI(renderer=lambda context: "<h1>Host login</h1>")
    adapter = FastAPIAuth(auth.backend, auth.manager, origin="https://example.test", ui=ui)
    app = FastAPI()
    app.include_router(adapter.router)
    with TestClient(app, base_url="https://example.test") as client:
        page = client.get("/auth/")
        assert page.status_code == (404 if mode == "headless" else 200)
        if mode == "override":
            assert "Host login" in page.text
        payload = {"username": "alice@example.invalid", "password": PASSWORD}
        assert client.post("/auth/login", json=payload).status_code == 403
        response = client.post("/auth/login", json=payload, headers={"Origin": "https://example.test"})
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "user"
        assert client.get("/auth/session").json()["authenticated"] is True
        assert client.post("/auth/logout", headers={"Origin": "https://example.test"}).status_code == 403
        assert client.post("/auth/logout", headers={"Origin": "https://example.test", "X-CSRF-Token": response.json()["csrf_token"]}).status_code == 200
