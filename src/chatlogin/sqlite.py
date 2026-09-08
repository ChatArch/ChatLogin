"""Small durable SQLite session store; never creates a user database."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3

from .identity import Principal
from .paths import state_paths
from .sessions import Session, StoreFull


def _private_parents(directory: Path) -> None:
    if directory.exists():
        return
    _private_parents(directory.parent)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        pass


class SQLiteSessionStore:
    """Synchronous store, one short connection per operation, atomic replacement.

    Supply a dedicated database or call for_instance(). Existing parent modes are
    not changed. Use a trusted, local filesystem (not a shared/network drive).
    """
    def __init__(self, database: str | Path, *, max_sessions: int = 100_000):
        if max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.database = Path(database)
        self.max_sessions = max_sessions
        _private_parents(self.database.parent)
        try:
            fd = os.open(self.database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.database.is_symlink() or not self.database.is_file():
                raise ValueError("Session database must be a regular, non-symlink file")
        else:
            os.close(fd)
        with self._connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS chatlogin_sessions (
                instance TEXT NOT NULL, digest TEXT NOT NULL,
                principal TEXT NOT NULL, expires_at REAL NOT NULL, csrf TEXT NOT NULL,
                PRIMARY KEY (instance, digest))""")
            conn.execute("CREATE INDEX IF NOT EXISTS chatlogin_expiry ON chatlogin_sessions(instance, expires_at)")

    @classmethod
    def for_instance(cls, instance: str, *, home=None, max_sessions: int = 100_000):
        return cls(state_paths(instance, home=home).database, max_sessions=max_sessions)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.database, timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def put(self, instance, digest, session, *, previous_digest=None):
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if previous_digest:
                conn.execute("DELETE FROM chatlogin_sessions WHERE instance=? AND digest=?", (instance, previous_digest))
            count = conn.execute("SELECT count(*) FROM chatlogin_sessions WHERE instance=?", (instance,)).fetchone()[0]
            if count >= self.max_sessions:
                raise StoreFull("Session capacity exhausted")
            conn.execute("INSERT INTO chatlogin_sessions VALUES (?, ?, ?, ?, ?)",
                         (instance, digest, json.dumps(session.principal.as_dict()), session.expires_at, session.csrf_token))

    def get(self, instance, digest):
        with self._connection() as conn:
            row = conn.execute("SELECT principal, expires_at, csrf FROM chatlogin_sessions WHERE instance=? AND digest=?", (instance, digest)).fetchone()
        return Session(Principal(**json.loads(row[0])), row[1], row[2]) if row else None

    def delete(self, instance, digest):
        with self._connection() as conn:
            conn.execute("DELETE FROM chatlogin_sessions WHERE instance=? AND digest=?", (instance, digest))

    def purge_expired(self, instance, now):
        with self._connection() as conn:
            conn.execute("DELETE FROM chatlogin_sessions WHERE instance=? AND expires_at<=?", (instance, now))
