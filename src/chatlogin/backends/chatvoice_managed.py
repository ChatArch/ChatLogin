"""ManagedUsers facade for ChatVoice's legacy accounts/auth_sessions tables.

The host must call ``initialize()`` explicitly before constructing ManagedUsers.
No production path, connection, or schema is touched on import.
"""
from __future__ import annotations

from contextlib import closing, contextmanager, nullcontext
from datetime import datetime, timezone
import sqlite3
from typing import Callable, ContextManager, Iterator

from ..credentials import PasswordHash
from ..identity import Role
from ..managed import (
    ManagedConflictError,
    ManagedNotFoundError,
    SQLiteUserStore,
    UserRecord,
    _canonical_username,
)


INSTANCE = "chatvoice"
PASSWORD_ITERATIONS = 310_000


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


_MANAGED_SCHEMA_STATEMENTS = (
    """
    CREATE VIEW IF NOT EXISTS chatlogin_managed_users AS
    SELECT
        'chatvoice' AS account_instance,
        id AS user_id,
        account AS username,
        lower(account) AS username_key,
        display_name AS display_name,
        role AS role,
        enabled AS enabled,
        deleted AS deleted,
        password_salt AS password_salt,
        password_hash AS password_digest,
        password_iterations AS password_iterations,
        auth_revision AS auth_revision,
        coalesce(unixepoch(created_at), 0) AS created_at,
        coalesce(unixepoch(updated_at), coalesce(unixepoch(created_at), 0)) AS updated_at
    FROM accounts
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chatlogin_managed_users_insert
    INSTEAD OF INSERT ON chatlogin_managed_users
    BEGIN
        SELECT CASE WHEN NEW.account_instance != 'chatvoice' THEN RAISE(ABORT, 'invalid account instance') END;
        INSERT INTO accounts (
            id, account, display_name, role, enabled, deleted,
            password_salt, password_hash, password_iterations,
            auth_revision, created_at, updated_at
        ) VALUES (
            NEW.user_id, NEW.username_key, NEW.display_name, NEW.role, NEW.enabled, NEW.deleted,
            NEW.password_salt, NEW.password_digest, NEW.password_iterations,
            NEW.auth_revision,
            strftime('%Y-%m-%dT%H:%M:%f+00:00', NEW.created_at, 'unixepoch'),
            strftime('%Y-%m-%dT%H:%M:%f+00:00', NEW.updated_at, 'unixepoch')
        );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chatlogin_managed_users_update
    INSTEAD OF UPDATE ON chatlogin_managed_users
    BEGIN
        SELECT CASE WHEN NEW.account_instance != 'chatvoice' THEN RAISE(ABORT, 'invalid account instance') END;
        UPDATE accounts SET
            account = NEW.username_key,
            display_name = NEW.display_name,
            role = NEW.role,
            enabled = NEW.enabled,
            deleted = NEW.deleted,
            password_salt = NEW.password_salt,
            password_hash = NEW.password_digest,
            password_iterations = NEW.password_iterations,
            auth_revision = NEW.auth_revision,
            updated_at = strftime('%Y-%m-%dT%H:%M:%f+00:00', NEW.updated_at, 'unixepoch')
        WHERE id = OLD.user_id;
    END
    """,
    """
    CREATE VIEW IF NOT EXISTS chatlogin_managed_sessions AS
    SELECT
        'chatvoice' AS account_instance,
        'chatvoice' AS session_namespace,
        token_hash AS digest,
        user_id AS user_id,
        auth_revision AS auth_revision,
        coalesce(unixepoch(expires_at), 0) AS expires_at,
        csrf_token AS csrf
    FROM auth_sessions
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chatlogin_managed_sessions_insert
    INSTEAD OF INSERT ON chatlogin_managed_sessions
    BEGIN
        SELECT CASE WHEN NEW.account_instance != 'chatvoice' OR NEW.session_namespace != 'chatvoice'
            THEN RAISE(ABORT, 'invalid session namespace') END;
        INSERT INTO auth_sessions (token_hash, user_id, csrf_token, created_at, expires_at, auth_revision)
        VALUES (
            NEW.digest, NEW.user_id, NEW.csrf,
            strftime('%Y-%m-%dT%H:%M:%f+00:00', unixepoch(), 'unixepoch'),
            strftime('%Y-%m-%dT%H:%M:%f+00:00', NEW.expires_at, 'unixepoch'),
            NEW.auth_revision
        );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chatlogin_managed_sessions_delete
    INSTEAD OF DELETE ON chatlogin_managed_sessions
    BEGIN
        DELETE FROM auth_sessions WHERE token_hash = OLD.digest;
    END
    """,
)


def initialize_chatvoice_managed_schema(connection: sqlite3.Connection) -> None:
    """Upgrade an already-open ChatVoice host connection for managed accounts."""
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("connection must be a sqlite3.Connection")
    store = ChatVoiceManagedStore(lambda: connection, lambda: nullcontext(), lambda: 0.0)
    store._initialize(connection)


class ChatVoiceManagedStore(SQLiteUserStore):
    """SQLiteUserStore-compatible facade backed by ChatVoice legacy tables."""

    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection],
        lock: Callable[[], ContextManager],
        clock: Callable[[], float],
        *,
        max_users: int = 10_000,
        max_sessions: int = 10_000,
    ):
        self._configure(INSTANCE, max_users=max_users, max_sessions=max_sessions)
        self.connect = connect
        self.lock = lock
        self.clock = clock
        self.database = None
        self._memory = False
        self._dummy = PasswordHash(b"\0" * 16, b"\0" * 32, PASSWORD_ITERATIONS)

    def close(self) -> None:
        self._closed = True

    @contextmanager
    def _connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        if self._closed:
            raise ValueError("Managed user store is closed")
        with self.lock(), closing(self.connect()) as connection:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            else:
                connection.commit()

    def initialize(self) -> None:
        """Add explicit managed metadata and facade objects idempotently."""
        with self._connection(immediate=True) as connection:
            self._initialize(connection)

    def _initialize(self, connection: sqlite3.Connection | None = None) -> None:
        owns_connection = connection is None
        manager = self._connection(immediate=True) if owns_connection else nullcontext(connection)
        with manager as db:
            account_columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()}
            if "role" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
            if "enabled" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            if "deleted" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
            if "auth_revision" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN auth_revision INTEGER NOT NULL DEFAULT 0")
            if "updated_at" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN updated_at TEXT")
                db.execute("UPDATE accounts SET updated_at = created_at WHERE updated_at IS NULL")
            if "password_iterations" not in account_columns:
                db.execute(
                    "ALTER TABLE accounts ADD COLUMN password_iterations INTEGER NOT NULL DEFAULT "
                    f"{PASSWORD_ITERATIONS}"
                )
            if db.execute(
                "SELECT lower(account) FROM accounts GROUP BY lower(account) HAVING count(*) > 1 LIMIT 1"
            ).fetchone():
                raise ManagedConflictError("Legacy account directory contains ambiguous account names")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS chatvoice_accounts_username_key "
                "ON accounts(lower(account))"
            )
            session_columns = {row[1] for row in db.execute("PRAGMA table_info(auth_sessions)").fetchall()}
            if "auth_revision" not in session_columns:
                db.execute("ALTER TABLE auth_sessions ADD COLUMN auth_revision INTEGER NOT NULL DEFAULT 0")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS chatvoice_accounts_one_owner "
                "ON accounts(role) WHERE role='owner' AND deleted=0"
            )
            for statement in _MANAGED_SCHEMA_STATEMENTS:
                db.execute(statement)


def adopt_owner(store: ChatVoiceManagedStore, existing_account_or_id: str) -> UserRecord:
    """Promote one exact existing legacy account to owner when no owner exists."""
    if not isinstance(store, ChatVoiceManagedStore):
        raise TypeError("adopt_owner requires a ChatVoiceManagedStore")
    try:
        account_key = _canonical_username(existing_account_or_id)
    except Exception:
        account_key = None
    with store._connection(immediate=True) as connection:
        store._initialize(connection)
        if connection.execute("SELECT 1 FROM accounts WHERE role=?", (Role.OWNER.value,)).fetchone():
            raise ManagedConflictError("A managed owner already exists")
        if account_key is None:
            rows = connection.execute(
                "SELECT DISTINCT id FROM accounts WHERE id=?",
                (existing_account_or_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT DISTINCT id FROM accounts WHERE id=? OR lower(account)=? ORDER BY id",
                (existing_account_or_id, account_key),
            ).fetchall()
        if not rows:
            raise ManagedNotFoundError()
        if len(rows) > 1:
            raise ManagedConflictError("Owner adoption selector matches multiple accounts")
        user_id = rows[0]["id"] if isinstance(rows[0], sqlite3.Row) else rows[0][0]
        now = _iso(store.clock())
        connection.execute(
            "UPDATE accounts SET role=?, enabled=1, deleted=0, auth_revision=auth_revision+1, updated_at=? "
            "WHERE id=?",
            (Role.OWNER.value, now, user_id),
        )
        connection.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
        return store._record(store._user_by_id(connection, user_id))


__all__ = ["ChatVoiceManagedStore", "adopt_owner", "initialize_chatvoice_managed_schema"]
