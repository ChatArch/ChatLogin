"""Synthetic legacy ChatVoice directory adapter tests."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3
import threading

import pytest

import chatlogin as cl
from chatlogin.backends.chatvoice import ChatVoiceAuth
from chatlogin.backends.chatvoice_managed import ChatVoiceManagedStore, adopt_owner, initialize_chatvoice_managed_schema


PASSWORD = "synthetic-test-password"
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _digest(password: str, salt: bytes, *, iterations: int = 310000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)


def _legacy_db(path):
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE accounts (
                id TEXT PRIMARY KEY,
                account TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                csrf_token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            """
        )
        for name in ("alice", "bob", "carol"):
            salt = name.encode().ljust(16, b"x")
            db.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "usr_" + name,
                    name + "@example.invalid",
                    name.title(),
                    salt,
                    _digest(PASSWORD, salt),
                    NOW.isoformat(),
                ),
            )


def _store(path):
    lock = threading.RLock()

    def connect():
        connection = sqlite3.connect(path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def locked():
        with lock:
            yield

    return ChatVoiceManagedStore(connect, locked, lambda: NOW.timestamp())


def test_upgrade_is_explicit_idempotent_and_preserves_legacy_identity_and_hash_bytes(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    with sqlite3.connect(path) as db:
        before = db.execute(
            "SELECT id, account, display_name, password_salt, password_hash, created_at FROM accounts ORDER BY id"
        ).fetchall()

    store = _store(path)
    store.initialize()
    store.initialize()

    with sqlite3.connect(path) as db:
        after = db.execute(
            "SELECT id, account, display_name, password_salt, password_hash, created_at FROM accounts ORDER BY id"
        ).fetchall()
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()}
    assert after == before
    assert {"role", "enabled", "deleted", "auth_revision", "updated_at"}.issubset(columns)
    assert cl.ManagedUsers(store).authenticate("alice@example.invalid", PASSWORD).user_id == "usr_alice"


def test_schema_initializer_preserves_outer_transaction_and_rolls_back(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    db = sqlite3.connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        initialize_chatvoice_managed_schema(db)
        assert db.in_transaction
        db.rollback()
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()}
        objects = {row[0] for row in db.execute("SELECT name FROM sqlite_master").fetchall()}
        assert "role" not in columns
        assert "chatlogin_managed_users" not in objects
        db.execute("BEGIN IMMEDIATE")
        initialize_chatvoice_managed_schema(db)
        initialize_chatvoice_managed_schema(db)
        assert db.in_transaction
        db.commit()
    finally:
        db.close()
    with sqlite3.connect(path) as check:
        columns = {row[1] for row in check.execute("PRAGMA table_info(accounts)").fetchall()}
    assert "role" in columns


def test_explicit_owner_adoption_and_shared_policy_matrix(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    store = _store(path)
    store.initialize()
    owner = adopt_owner(store, "alice@example.invalid")
    assert owner.user_id == "usr_alice"
    with pytest.raises(cl.ManagedConflictError):
        adopt_owner(store, "bob@example.invalid")

    users = cl.ManagedUsers(store)
    owner_principal = users.authenticate("alice@example.invalid", PASSWORD)
    admin = users.update_user(owner_principal, "usr_bob", role=cl.Role.ADMIN)
    assert admin.role is cl.Role.ADMIN
    admin_principal = users.authenticate("bob@example.invalid", PASSWORD)
    with pytest.raises(cl.ManagedPermissionError):
        users.update_user(admin_principal, "usr_bob", role=cl.Role.USER)
    with pytest.raises(cl.ManagedPermissionError):
        users.get_user(admin_principal, "usr_alice")
    users.update_user(admin_principal, "usr_carol", enabled=False)
    assert users.authenticate("carol@example.invalid", PASSWORD) is None


def test_owner_adoption_rejects_selector_matching_id_and_other_account(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE accounts SET id=? WHERE id=?",
            ("bob@example.invalid", "usr_alice"),
        )
        db.execute(
            "INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?)",
            ("a" * 64, "bob@example.invalid", "s" * 32, NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()),
        )
        before_accounts = db.execute(
            "SELECT id, account, display_name, password_salt, password_hash, created_at FROM accounts ORDER BY account"
        ).fetchall()
        before_sessions = db.execute("SELECT * FROM auth_sessions ORDER BY token_hash").fetchall()

    store = _store(path)
    with pytest.raises(cl.ManagedConflictError):
        adopt_owner(store, "bob@example.invalid")

    with sqlite3.connect(path) as db:
        after_accounts = db.execute(
            "SELECT id, account, display_name, password_salt, password_hash, created_at FROM accounts ORDER BY account"
        ).fetchall()
        after_sessions = db.execute("SELECT * FROM auth_sessions ORDER BY token_hash").fetchall()
    assert after_accounts == before_accounts
    assert after_sessions == before_sessions


def test_owner_adoption_accepts_same_account_by_id_or_account(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE accounts SET id=account WHERE account='alice@example.invalid'")
        db.commit()

    store = _store(path)
    owner = adopt_owner(store, "alice@example.invalid")
    assert owner.user_id == "alice@example.invalid"


def test_owner_adoption_rolls_back_if_post_update_fails(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    store = _store(path)
    original = store._record

    def fail_once(row):
        if row[0] == "usr_alice":
            raise RuntimeError("synthetic failure after owner update")
        return original(row)

    monkeypatch.setattr(store, "_record", fail_once)
    with pytest.raises(RuntimeError):
        adopt_owner(store, "alice@example.invalid")
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()}
        if "role" in columns:
            assert db.execute("SELECT count(*) FROM accounts WHERE role='owner'").fetchone()[0] == 0


def test_initializer_rejects_lower_account_collisions_and_rolls_back(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    with sqlite3.connect(path) as db:
        salt = b"collision-salt!!"
        db.execute(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)",
            ("usr_collision", "ALICE@example.invalid", "Collision", salt, _digest(PASSWORD, salt), NOW.isoformat()),
        )
        before = db.execute(
            "SELECT id, account, display_name, password_salt, password_hash, created_at FROM accounts ORDER BY id"
        ).fetchall()

    store = _store(path)
    with pytest.raises(cl.ManagedConflictError):
        store.initialize()

    with sqlite3.connect(path) as db:
        after = db.execute(
            "SELECT id, account, display_name, password_salt, password_hash, created_at FROM accounts ORDER BY id"
        ).fetchall()
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()}
    assert after == before
    assert "role" not in columns


def test_initializer_unique_index_blocks_new_case_collisions(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    _store(path).initialize()
    with sqlite3.connect(path) as db:
        salt = b"new-collision!!"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO accounts (id, account, display_name, password_salt, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("usr_new_collision", "ALICE@example.invalid", "Collision", salt, _digest(PASSWORD, salt), NOW.isoformat()),
            )


def test_revision_bound_sessions_and_password_reset_invalidate_legacy_rows(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    store = _store(path)
    store.initialize()
    adopt_owner(store, "alice@example.invalid")
    users = cl.ManagedUsers(store, ttl=30 * 24 * 60 * 60)

    owner_principal = users.authenticate("alice@example.invalid", PASSWORD)
    issued = users.sessions.issue(owner_principal)
    digest = users.sessions.digest(issued.token)
    with closing(store.connect()) as db:
        row = db.execute("SELECT user_id, auth_revision FROM auth_sessions WHERE token_hash=?", (digest,)).fetchone()
    assert dict(row) == {"user_id": "usr_alice", "auth_revision": 1}

    users.change_password(owner_principal, PASSWORD, "new-synthetic-password")
    assert users.sessions.resolve(issued.token) is None
    assert users.authenticate("alice@example.invalid", PASSWORD) is None
    assert users.authenticate("alice@example.invalid", "new-synthetic-password").user_id == "usr_alice"


def test_chatvoice_auth_rechecks_revision_status_and_uses_stored_iterations(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    store = _store(path)
    store.initialize()
    adopt_owner(store, "alice@example.invalid")
    salt = b"custom-iterations"
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE accounts SET password_salt=?, password_hash=?, password_iterations=? WHERE id='usr_alice'",
            (salt, _digest("iteration-password", salt, iterations=7), 7),
        )
        db.commit()

    auth = ChatVoiceAuth(lambda: store.connect(), lambda: store.lock(), lambda: NOW.timestamp(), ttl=3600)
    stale = auth.backend.authenticate("alice@example.invalid", "iteration-password")
    assert isinstance(stale, cl.ManagedPrincipal)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE accounts SET auth_revision=auth_revision+1 WHERE id='usr_alice'")
        db.commit()
    with pytest.raises(cl.ManagedPermissionError):
        auth.manager.issue(stale)

    current = auth.backend.authenticate("alice@example.invalid", "iteration-password")
    issued = auth.manager.issue(current)
    resolved = auth.manager.resolve(issued.token)
    assert isinstance(resolved.principal, cl.ManagedPrincipal)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE accounts SET enabled=0, auth_revision=auth_revision+1 WHERE id='usr_alice'")
        db.commit()
    assert auth.manager.resolve(issued.token) is None


def test_no_import_side_effect_on_host_schema(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _legacy_db(path)
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    __import__("chatlogin.backends.chatvoice_managed")
    with sqlite3.connect(path) as db:
        after = db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    assert after == before
