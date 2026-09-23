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
from ..security import require_csrf
from ..sessions import Session, SessionManager, StoreFull

INSTANCE = "chatvoice"
PASSWORD_ITERATIONS = 310_000


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _principal(row) -> Principal:
    return Principal(row["user_id"], row["display_name"], Role.USER)


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
        if not isinstance(session, Session) or session.principal.role is not Role.USER:
            raise ValueError("ChatVoice sessions require a validated ordinary user")
        with self.lock(), closing(self.connect()) as db, db:
            # SQLite also serializes capacity/replacement across processes.
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM auth_sessions WHERE token_hash = ?", (digest,)).fetchone():
                raise ValueError("Session digest already exists")
            replaces = db.execute("SELECT 1 FROM auth_sessions WHERE token_hash = ?", (previous_digest,)).fetchone()
            if db.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] >= self.max_sessions and not replaces:
                raise StoreFull("Session capacity exhausted")
            if replaces:
                db.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (previous_digest,))
            db.execute("INSERT INTO auth_sessions (token_hash, user_id, csrf_token, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                       (digest, session.principal.user_id, session.csrf_token,
                        _iso(self.clock()), _iso(session.expires_at)))

    def read_row(self, instance, digest):
        self._namespace(instance)
        with self.lock(), closing(self.connect()) as db:
            return db.execute("""SELECT s.token_hash, s.user_id, s.csrf_token, s.expires_at,
                                 a.account, a.display_name FROM auth_sessions s
                                 JOIN accounts a ON a.id = s.user_id WHERE s.token_hash = ?""",
                              (digest,)).fetchone()

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
            row = db.execute("SELECT id AS user_id, display_name, password_salt, password_hash FROM accounts WHERE account = ?", (account,)).fetchone()
        # Missing users still incur the same legacy PBKDF2 work; no dummy account.
        salt, digest = (row["password_salt"], row["password_hash"]) if row else (b"\0" * 16, b"\0" * 32)
        valid = verify_pbkdf2(password, salt, digest, iterations=PASSWORD_ITERATIONS)
        return _principal(row) if row and valid else None

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
