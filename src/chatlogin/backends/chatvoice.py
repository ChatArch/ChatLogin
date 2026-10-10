"""Optional compatibility backend for ChatVoice's existing SQLite auth schema.

No ChatVoice or web dependency, schema creation, migration, or account management.
The host supplies fresh sqlite3.Row connections (with foreign keys enabled), a
lock context-manager callback, and a UTC timestamp callback. Callbacks are invoked
at operation time, so changing host paths, locks, or clocks is not captured here.
No store method calls another store method while holding the host lock.
"""
from contextlib import closing
from datetime import datetime, timezone
from typing import Callable, ContextManager
import sqlite3

from ..credentials import CallbackBackend, verify_pbkdf2
from ..identity import Principal, Role
from ..managed import ManagedPermissionError, ManagedPrincipal
from ..security import require_csrf
from ..sessions import Session, SessionManager, StoreFull

INSTANCE = "chatvoice"
PASSWORD_ITERATIONS = 310_000


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _has_column(row, name: str) -> bool:
    return hasattr(row, "keys") and name in row.keys()


def _principal(row) -> Principal:
    role = Role(row["role"]) if _has_column(row, "role") else Role.USER
    if _has_column(row, "auth_revision"):
        return ManagedPrincipal(row["user_id"], row["display_name"], role, int(row["auth_revision"]))
    if _has_column(row, "account_auth_revision"):
        return ManagedPrincipal(row["user_id"], row["display_name"], role, int(row["account_auth_revision"]))
    return Principal(row["user_id"], row["display_name"], role)


def _table_columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _valid_iterations(value) -> int:
    try:
        iterations = int(value)
    except (TypeError, ValueError):
        return PASSWORD_ITERATIONS
    return iterations if 1 <= iterations <= 10_000_000 else PASSWORD_ITERATIONS


class ChatVoiceSessionStore:
    """Use ChatVoice accounts/auth_sessions as one fixed ``chatvoice`` namespace.

    Implements SessionStore without creating tables or changing password material.
    Capacity is database-wide, including unpurged expired rows; SessionManager
    purges before issuing. Replacement and capacity checks share one transaction.
    Each connection returned by ``connect`` is closed after the operation.
    """

    def __init__(self, connect: Callable[[], sqlite3.Connection],
                 lock: Callable[[], ContextManager], clock: Callable[[], float],
                 *, max_sessions: int = 10_000):
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.connect, self.lock, self.clock = connect, lock, clock
        self.max_sessions = max_sessions

    @staticmethod
    def _namespace(instance):
        if instance != INSTANCE:
            raise ValueError("This host database is reserved for chatvoice")

    def put(self, instance, digest, session, *, previous_digest=None):
        self._namespace(instance)
        if not isinstance(session, Session):
            raise ValueError("ChatVoice sessions require an ordinary user or verified managed user")
        with self.lock(), closing(self.connect()) as db, db:
            # SQLite also serializes capacity/replacement across processes.
            db.execute("BEGIN IMMEDIATE")
            account_columns = _table_columns(db, "accounts")
            metadata = {"role", "enabled", "deleted", "auth_revision"}.issubset(account_columns)
            if metadata:
                if not isinstance(session.principal, ManagedPrincipal):
                    raise ManagedPermissionError("ChatVoice managed sessions require revision-bound principals")
                live = db.execute(
                    "SELECT id AS user_id, display_name, role, enabled, deleted, auth_revision "
                    "FROM accounts WHERE id = ?",
                    (session.principal.user_id,),
                ).fetchone()
                if (live is None or bool(live["deleted"]) or not bool(live["enabled"])
                        or live["role"] != session.principal.role.value
                        or int(live["auth_revision"]) != session.principal.auth_revision):
                    raise ManagedPermissionError("ChatVoice session principal is no longer valid")
            elif session.principal.role is not Role.USER:
                raise ValueError("ChatVoice legacy sessions require an ordinary user")
            if db.execute("SELECT 1 FROM auth_sessions WHERE token_hash = ?", (digest,)).fetchone():
                raise ValueError("Session digest already exists")
            replaces = db.execute("SELECT 1 FROM auth_sessions WHERE token_hash = ?", (previous_digest,)).fetchone()
            if db.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] >= self.max_sessions and not replaces:
                raise StoreFull("Session capacity exhausted")
            if replaces:
                db.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (previous_digest,))
            if metadata and "auth_revision" in _table_columns(db, "auth_sessions"):
                db.execute(
                    "INSERT INTO auth_sessions (token_hash, user_id, csrf_token, created_at, expires_at, auth_revision) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (digest, session.principal.user_id, session.csrf_token,
                     _iso(self.clock()), _iso(session.expires_at), int(session.principal.auth_revision)),
                )
            else:
                db.execute("INSERT INTO auth_sessions (token_hash, user_id, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                           (digest, session.principal.user_id, session.csrf_token,
                            _iso(self.clock()), _iso(session.expires_at)))

    def read_row(self, instance, digest):
        self._namespace(instance)
        with self.lock(), closing(self.connect()) as db:
            account_columns = _table_columns(db, "accounts")
            session_columns = _table_columns(db, "auth_sessions")
            account_select = ["a.account", "a.display_name"]
            if {"role", "enabled", "deleted", "auth_revision"}.issubset(account_columns):
                account_select.extend([
                    "a.role", "a.enabled", "a.deleted", "a.auth_revision AS account_auth_revision",
                    "a.auth_revision",
                ])
            session_select = ["s.token_hash", "s.user_id", "s.csrf_token", "s.expires_at"]
            if "auth_revision" in session_columns:
                session_select.append("s.auth_revision AS session_auth_revision")
            row = db.execute(
                f"SELECT {', '.join(session_select + account_select)} FROM auth_sessions s "
                "JOIN accounts a ON a.id = s.user_id WHERE s.token_hash = ?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        if _has_column(row, "deleted") and (bool(row["deleted"]) or not bool(row["enabled"])):
            self.delete(instance, digest)
            return None
        if (_has_column(row, "account_auth_revision") and _has_column(row, "session_auth_revision")
                and int(row["account_auth_revision"]) != int(row["session_auth_revision"])):
            self.delete(instance, digest)
            return None
        return row

    @staticmethod
    def session_from_row(row):
        return Session(_principal(row), datetime.fromisoformat(row["expires_at"]).timestamp(), row["csrf_token"])

    def get(self, instance, digest):
        row = self.read_row(instance, digest)
        if row is None:
            return None
        try:
            return self.session_from_row(row)
        except (ValueError, TypeError, OverflowError):
            # Corrupt host sessions fail closed, never become an identity.
            self.delete(instance, digest)
            return None

    def delete(self, instance, digest):
        self._namespace(instance)
        with self.lock(), closing(self.connect()) as db, db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (digest,))

    def purge_expired(self, instance, now):
        self._namespace(instance)
        with self.lock(), closing(self.connect()) as db, db:
            # julianday understands legacy ISO offsets, unlike lexical comparison.
            db.execute("DELETE FROM auth_sessions WHERE julianday(expires_at) <= julianday(?) OR julianday(expires_at) IS NULL", (_iso(now),))


class ChatVoiceAuth:
    """Ready-made ChatVoice schema bridge; HTTP, UI and owner policy stay outside.

    ``login`` returns IssuedSession or None; ``resolve_row`` returns the current
    joined account/session mapping or None, with ``_chatlogin_session`` for CSRF.
    ``backend`` and ``manager`` can also be passed directly to FastAPIAuth.
    """

    def __init__(self, connect, lock, clock, *, ttl, max_sessions=10_000):
        self.store = ChatVoiceSessionStore(connect, lock, clock, max_sessions=max_sessions)
        self.backend = CallbackBackend(self._authenticate)
        self.manager = SessionManager(self.store, instance=INSTANCE, ttl=ttl, clock=clock)

    def _authenticate(self, account, password):
        with self.store.lock(), closing(self.store.connect()) as db:
            columns = _table_columns(db, "accounts")
            extra = ""
            if {"role", "enabled", "deleted", "auth_revision"}.issubset(columns):
                extra = ", role, enabled, deleted, auth_revision"
            if "password_iterations" in columns:
                extra += ", password_iterations"
            row = db.execute(
                "SELECT id AS user_id, display_name, password_salt, password_hash" + extra
                + " FROM accounts WHERE account = ?",
                (account,),
            ).fetchone()
        # Missing users still incur the same legacy PBKDF2 work; no dummy account.
        salt, digest = (row["password_salt"], row["password_hash"]) if row else (b"\0" * 16, b"\0" * 32)
        iterations = _valid_iterations(row["password_iterations"]) if row and _has_column(row, "password_iterations") else PASSWORD_ITERATIONS
        valid = verify_pbkdf2(password, salt, digest, iterations=iterations)
        if not row or not valid:
            return None
        if _has_column(row, "deleted") and (bool(row["deleted"]) or not bool(row["enabled"])):
            return None
        return _principal(row)

    def login(self, account, password):
        principal = self.backend.authenticate(account, password)
        return self.manager.issue(principal) if principal is not None else None

    def resolve_row(self, token):
        session = self.manager.resolve(token)
        if session is None:
            return None
        # Rejoin the account for business payloads, never cache an account snapshot.
        row = self.store.read_row(INSTANCE, self.manager.digest(token))
        if row is None:
            return None
        result = dict(row)
        result["_chatlogin_session"] = session
        return result

    def check_csrf(self, auth, submitted):
        require_csrf(auth["_chatlogin_session"], submitted)

    def logout(self, token):
        self.manager.revoke(token)
