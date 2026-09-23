"""Small durable SQLite session store; never creates a user database."""
from pathlib import Path
import json

from .identity import Principal
from .paths import state_paths
from .private_sqlite import PrivateSQLite
from .sessions import Session, StoreFull


class SQLiteSessionStore:
    """Synchronous store, one short connection per operation, atomic replacement.

    Supply a dedicated database or call for_instance(). Existing paths are not
    made private retroactively. Use a trusted local filesystem; same-UID
    processes are inside that filesystem trust boundary. max_sessions bounds
    the entire database across instances, not each namespace. All handles
    sharing a database must configure the same capacity.
    """

    def __init__(self, database: str | Path, *, max_sessions: int = 100_000):
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.database = Path(database)
        self.max_sessions = max_sessions
        self._sqlite = PrivateSQLite(self.database)
        with self._connection() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS chatlogin_sessions (
                instance TEXT NOT NULL, digest TEXT NOT NULL,
                principal TEXT NOT NULL, expires_at REAL NOT NULL, csrf TEXT NOT NULL,
                PRIMARY KEY (instance, digest))""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS chatlogin_expiry "
                "ON chatlogin_sessions(instance, expires_at)"
            )

    @classmethod
    def for_instance(cls, instance: str, *, home=None, max_sessions: int = 100_000):
        return cls(state_paths(instance, home=home).database, max_sessions=max_sessions)

    def _connection(self, *, immediate: bool = False):
        return self._sqlite.connect(immediate=immediate)

    def put(self, instance, digest, session, *, previous_digest=None):
        if not isinstance(session, Session):
            raise ValueError("Session store requires a validated Session")
        with self._connection(immediate=True) as connection:
            if connection.execute(
                "SELECT 1 FROM chatlogin_sessions WHERE instance=? AND digest=?",
                (instance, digest),
            ).fetchone():
                raise ValueError("Session digest already exists")
            if previous_digest:
                connection.execute(
                    "DELETE FROM chatlogin_sessions WHERE instance=? AND digest=?",
                    (instance, previous_digest),
                )
            count = connection.execute(
                "SELECT count(*) FROM chatlogin_sessions"
            ).fetchone()[0]
            if count >= self.max_sessions:
                raise StoreFull("Session capacity exhausted")
            connection.execute(
                "INSERT INTO chatlogin_sessions VALUES (?, ?, ?, ?, ?)",
                (instance, digest, json.dumps(session.principal.as_dict()),
                 session.expires_at, session.csrf_token),
            )

    def get(self, instance, digest):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT principal, expires_at, csrf FROM chatlogin_sessions "
                "WHERE instance=? AND digest=?",
                (instance, digest),
            ).fetchone()
        return Session(Principal(**json.loads(row[0])), row[1], row[2]) if row else None

    def delete(self, instance, digest):
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM chatlogin_sessions WHERE instance=? AND digest=?",
                (instance, digest),
            )

    def purge_expired(self, instance, now):
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM chatlogin_sessions WHERE instance=? AND expires_at<=?",
                (instance, now),
            )
