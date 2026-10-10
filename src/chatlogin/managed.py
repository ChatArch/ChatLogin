"""Private SQLite-backed managed accounts and revision-bound opaque sessions.

This module is deliberately library-only: it has no web-framework imports and
does not create a public bootstrap route.  Host applications decide how a
trusted operator invokes :meth:`ManagedUsers.bootstrap_owner`.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from typing import Iterator
import uuid

from .credentials import PasswordHash, hash_password, verify_pbkdf2
from .identity import Principal, Role
from .paths import state_paths, validate_instance
from .private_sqlite import PrivateSQLite
from .sessions import Session, SessionManager, StoreFull


MAX_USERS_DEFAULT = 10_000
MAX_SESSIONS_DEFAULT = 10_000
MAX_LIST_LIMIT = 100
MAX_USERNAME_BYTES = 80
MAX_DISPLAY_NAME_CHARS = 256
MAX_DISPLAY_NAME_BYTES = 1024
MAX_PASSWORD_BYTES = 1024
_USERNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._+@-]{1,78}[A-Za-z0-9])?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MANAGED_ROLES = frozenset((Role.OWNER, Role.ADMIN, Role.USER))


class ManagedError(Exception):
    """Base class for safe managed-user errors suitable for boundary mapping."""

    status_code = 400
    default_detail = "Managed user operation failed"

    def __init__(self, detail: str | None = None):
        self.detail = self.default_detail if detail is None else detail
        super().__init__(self.detail)


class ManagedValidationError(ManagedError, ValueError):
    status_code = 400
    default_detail = "Invalid managed user input"


class ManagedNotFoundError(ManagedError):
    status_code = 404
    default_detail = "Managed user was not found"


class ManagedConflictError(ManagedError):
    status_code = 409
    default_detail = "Managed user operation conflicts with current state"


class ManagedPermissionError(ManagedError):
    status_code = 403
    default_detail = "Managed user operation is not permitted"


# Short aliases are useful to thin Web/CLI adapters without exposing sqlite errors.
ValidationError = ManagedValidationError
NotFoundError = ManagedNotFoundError
ConflictError = ManagedConflictError
PermissionDenied = ManagedPermissionError


@dataclass(frozen=True)
class UserRecord:
    """Safe immutable account metadata; credential material is never present."""

    user_id: str
    username: str
    display_name: str
    role: Role
    enabled: bool
    deleted: bool
    created_at: float
    updated_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", Role(self.role))
        if self.role not in _MANAGED_ROLES:
            raise ValueError("UserRecord requires a managed role")
        if not isinstance(self.user_id, str) or not self.user_id:
            raise ValueError("UserRecord requires a user id")
        if not isinstance(self.username, str) or not self.username:
            raise ValueError("UserRecord requires a username")
        if type(self.enabled) is not bool or type(self.deleted) is not bool:
            raise ValueError("UserRecord status must be boolean")
        for value in (self.created_at, self.updated_at):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("UserRecord timestamps must be finite")


@dataclass(frozen=True)
class ManagedPrincipal(Principal):
    """A live-account principal carrying an unexported credential revision."""

    auth_revision: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.role not in _MANAGED_ROLES:
            raise ValueError("ManagedPrincipal requires a managed role")
        if type(self.auth_revision) is not int or self.auth_revision < 0:
            raise ValueError("ManagedPrincipal revision must be a nonnegative integer")


def _now() -> float:
    value = time.time()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RuntimeError("System clock must return a finite number")
    return float(value)


def _canonical_username(value: str) -> str:
    if not isinstance(value, str):
        raise ManagedValidationError("Username is invalid")
    try:
        encoded = value.encode("ascii")
    except UnicodeError as exc:
        raise ManagedValidationError("Username is invalid") from exc
    if (not 3 <= len(encoded) <= MAX_USERNAME_BYTES or not _USERNAME.fullmatch(value)
            or value.count("@") > 1 or ".." in value):
        raise ManagedValidationError("Username is invalid")
    return value.casefold()


def _valid_auth_password(value: object) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return False
    return 1 <= len(encoded) <= MAX_PASSWORD_BYTES


def _validate_new_password(value: str) -> None:
    if not _valid_auth_password(value):
        raise ManagedValidationError("Password is invalid")
    if len(value) < 8:
        raise ManagedValidationError("Password is invalid")


def _validate_display_name(value: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_DISPLAY_NAME_CHARS:
        raise ManagedValidationError("Display name is invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ManagedValidationError("Display name is invalid") from exc
    if (len(encoded) > MAX_DISPLAY_NAME_BYTES or "\x00" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ManagedValidationError("Display name is invalid")
    return value


def _managed_role(value: Role | str, *, creatable: bool = False) -> Role:
    if not isinstance(value, (Role, str)):
        raise ManagedValidationError("Role is invalid")
    try:
        role = Role(value)
    except ValueError as exc:
        raise ManagedValidationError("Role is invalid") from exc
    if role not in (Role.ADMIN, Role.USER):
        raise ManagedValidationError("Role is invalid")
    if creatable and role not in (Role.ADMIN, Role.USER):  # Kept explicit for call-site policy.
        raise ManagedValidationError("Role is invalid")
    return role


def _validate_user_id(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ManagedValidationError("User id is invalid")
    return value


def _validate_paging(offset: int, limit: int, maximum: int) -> tuple[int, int]:
    if type(offset) is not int or offset < 0 or offset > maximum:
        raise ManagedValidationError("Pagination is invalid")
    if type(limit) is not int or not 1 <= limit <= MAX_LIST_LIMIT:
        raise ManagedValidationError("Pagination is invalid")
    return offset, min(limit, maximum)


class _SharedMemorySQLite:
    """A keeper-backed shared-memory SQLite database with explicit lifetime."""

    def __init__(self) -> None:
        self._uri = f"file:chatlogin-managed-{uuid.uuid4().hex}?mode=memory&cache=shared"
        self._lock = threading.RLock()
        self._closed = False
        self._keeper = sqlite3.connect(self._uri, uri=True, timeout=5, check_same_thread=False)
        self._keeper.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        # Shared-cache in-memory SQLite returns SQLITE_LOCKED instead of honoring a
        # busy timeout in several concurrent cases.  Serializing short operations
        # preserves the same SQL transactions and makes test/demo lifetime bounded.
        with self._lock:
            if self._closed:
                raise ValueError("Managed user store is closed")
            connection = sqlite3.connect(self._uri, uri=True, timeout=5)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
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
            finally:
                connection.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._keeper.close()
                self._closed = True


class SQLiteUserStore:
    """Private account/session storage for exactly one managed account instance."""

    _USER_COLUMNS = (
        "user_id, username, display_name, role, enabled, deleted, created_at, updated_at, "
        "password_salt, password_digest, password_iterations, auth_revision"
    )

    def __init__(self, database: str | Path, *, instance: str,
                 max_users: int = MAX_USERS_DEFAULT, max_sessions: int = MAX_SESSIONS_DEFAULT):
        self._configure(instance, max_users=max_users, max_sessions=max_sessions)
        self.database: Path | None = Path(database)
        self._backend = PrivateSQLite(self.database)
        self._memory = False
        self._initialize()

    def _configure(self, instance: str, *, max_users: int, max_sessions: int) -> None:
        self.instance = validate_instance(instance)
        if type(max_users) is not int or max_users < 1:
            raise ValueError("max_users must be positive")
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.max_users = max_users
        self.max_sessions = max_sessions
        self._closed = False
        self._dummy = PasswordHash(secrets.token_bytes(16), secrets.token_bytes(32))

    @classmethod
    def for_instance(cls, instance: str, *, home=None, max_users: int = MAX_USERS_DEFAULT,
                     max_sessions: int = MAX_SESSIONS_DEFAULT) -> "SQLiteUserStore":
        paths = state_paths(instance, home=home)
        return cls(paths.users_database, instance=instance, max_users=max_users,
                   max_sessions=max_sessions)

    @classmethod
    def in_memory(cls, instance: str, *, max_users: int = MAX_USERS_DEFAULT,
                  max_sessions: int = MAX_SESSIONS_DEFAULT) -> "SQLiteUserStore":
        store = cls.__new__(cls)
        store._configure(instance, max_users=max_users, max_sessions=max_sessions)
        store.database = None
        store._backend = _SharedMemorySQLite()
        store._memory = True
        store._initialize()
        return store

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._memory:
            self._backend.close()

    def _connection(self, *, immediate: bool = False):
        if self._closed:
            raise ValueError("Managed user store is closed")
        return self._backend.connect(immediate=immediate)

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS chatlogin_managed_users (
                account_instance TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                username_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'user')),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
                password_salt BLOB NOT NULL CHECK (length(password_salt) >= 16),
                password_digest BLOB NOT NULL CHECK (length(password_digest) = 32),
                password_iterations INTEGER NOT NULL CHECK (password_iterations BETWEEN 1 AND 10000000),
                auth_revision INTEGER NOT NULL CHECK (auth_revision >= 0),
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (account_instance, user_id),
                UNIQUE (account_instance, username_key),
                CHECK (role != 'owner' OR (enabled = 1 AND deleted = 0))
            )""")
            connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS chatlogin_managed_one_owner
                ON chatlogin_managed_users(account_instance) WHERE role = 'owner'""")
            connection.execute("""CREATE TABLE IF NOT EXISTS chatlogin_managed_sessions (
                account_instance TEXT NOT NULL,
                session_namespace TEXT NOT NULL,
                digest TEXT NOT NULL,
                user_id TEXT NOT NULL,
                auth_revision INTEGER NOT NULL CHECK (auth_revision >= 0),
                expires_at REAL NOT NULL,
                csrf TEXT NOT NULL,
                PRIMARY KEY (account_instance, session_namespace, digest)
            )""")
            connection.execute("""CREATE INDEX IF NOT EXISTS chatlogin_managed_session_user
                ON chatlogin_managed_sessions(account_instance, user_id)""")
            connection.execute("""CREATE INDEX IF NOT EXISTS chatlogin_managed_session_expiry
                ON chatlogin_managed_sessions(account_instance, session_namespace, expires_at)""")

    @staticmethod
    def _record(row: tuple) -> UserRecord:
        return UserRecord(row[0], row[1], row[2], Role(row[3]), bool(row[4]), bool(row[5]), row[6], row[7])

    @staticmethod
    def _principal(row: tuple) -> ManagedPrincipal:
        return ManagedPrincipal(row[0], row[2], Role(row[3]), int(row[11]))

    def _user_by_id(self, connection: sqlite3.Connection, user_id: str) -> tuple | None:
        return connection.execute(
            f"SELECT {self._USER_COLUMNS} FROM chatlogin_managed_users "
            "WHERE account_instance=? AND user_id=?",
            (self.instance, user_id),
        ).fetchone()

    def _user_by_username(self, connection: sqlite3.Connection, username_key: str) -> tuple | None:
        return connection.execute(
            f"SELECT {self._USER_COLUMNS} FROM chatlogin_managed_users "
            "WHERE account_instance=? AND username_key=?",
            (self.instance, username_key),
        ).fetchone()

    def _invalidate_sessions(self, connection: sqlite3.Connection, user_id: str) -> None:
        connection.execute(
            "DELETE FROM chatlogin_managed_sessions WHERE account_instance=? AND user_id=?",
            (self.instance, user_id),
        )


class ManagedSessionStore:
    """SessionStore implementation which atomically rechecks a managed revision."""

    def __init__(self, store: SQLiteUserStore):
        if not isinstance(store, SQLiteUserStore):
            raise TypeError("ManagedSessionStore requires a SQLiteUserStore")
        self.store = store

    @staticmethod
    def _namespace(value: str) -> str:
        return validate_instance(value)

    @staticmethod
    def _digest(value: str) -> str:
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            raise ValueError("Session digest is invalid")
        return value

    def put(self, instance: str, digest: str, session: Session, *, previous_digest: str | None = None) -> None:
        namespace = self._namespace(instance)
        digest = self._digest(digest)
        if previous_digest is not None:
            previous_digest = self._digest(previous_digest)
        if not isinstance(session, Session) or not isinstance(session.principal, ManagedPrincipal):
            raise ManagedPermissionError("Managed session requires a verified managed principal")
        principal = session.principal
        try:
            with self.store._connection(immediate=True) as connection:
                row = self.store._user_by_id(connection, principal.user_id)
                if (row is None or bool(row[5]) or not bool(row[4])
                        or int(row[11]) != principal.auth_revision
                        or row[3] != principal.role.value):
                    raise ManagedPermissionError("Managed session principal is no longer valid")
                if connection.execute(
                    "SELECT 1 FROM chatlogin_managed_sessions "
                    "WHERE account_instance=? AND session_namespace=? AND digest=?",
                    (self.store.instance, namespace, digest),
                ).fetchone():
                    raise ValueError("Session digest already exists")
                if previous_digest is not None:
                    connection.execute(
                        "DELETE FROM chatlogin_managed_sessions "
                        "WHERE account_instance=? AND session_namespace=? AND digest=?",
                        (self.store.instance, namespace, previous_digest),
                    )
                count = connection.execute(
                    "SELECT count(*) FROM chatlogin_managed_sessions WHERE account_instance=?",
                    (self.store.instance,),
                ).fetchone()[0]
                if count >= self.store.max_sessions:
                    raise StoreFull("Session capacity exhausted")
                connection.execute(
                    "INSERT INTO chatlogin_managed_sessions "
                    "(account_instance, session_namespace, digest, user_id, auth_revision, expires_at, csrf) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (self.store.instance, namespace, digest, principal.user_id, principal.auth_revision,
                     session.expires_at, session.csrf_token),
                )
        except sqlite3.IntegrityError:
            raise ManagedConflictError() from None

    def get(self, instance: str, digest: str) -> Session | None:
        namespace = self._namespace(instance)
        digest = self._digest(digest)
        with self.store._connection(immediate=True) as connection:
            stored = connection.execute(
                "SELECT user_id, auth_revision, expires_at, csrf FROM chatlogin_managed_sessions "
                "WHERE account_instance=? AND session_namespace=? AND digest=?",
                (self.store.instance, namespace, digest),
            ).fetchone()
            if stored is None:
                return None
            row = self.store._user_by_id(connection, stored[0])
            if (row is None or bool(row[5]) or not bool(row[4])
                    or int(row[11]) != int(stored[1])):
                connection.execute(
                    "DELETE FROM chatlogin_managed_sessions "
                    "WHERE account_instance=? AND session_namespace=? AND digest=?",
                    (self.store.instance, namespace, digest),
                )
                return None
            return Session(self.store._principal(row), stored[2], stored[3])

    def delete(self, instance: str, digest: str) -> None:
        namespace = self._namespace(instance)
        digest = self._digest(digest)
        with self.store._connection(immediate=True) as connection:
            connection.execute(
                "DELETE FROM chatlogin_managed_sessions "
                "WHERE account_instance=? AND session_namespace=? AND digest=?",
                (self.store.instance, namespace, digest),
            )

    def purge_expired(self, instance: str, now: float) -> None:
        namespace = self._namespace(instance)
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError("Session expiry is invalid")
        with self.store._connection(immediate=True) as connection:
            connection.execute(
                "DELETE FROM chatlogin_managed_sessions "
                "WHERE account_instance=? AND session_namespace=? AND expires_at<=?",
                (self.store.instance, namespace, now),
            )


class ManagedUsers:
    """Managed account service and ``CredentialBackend`` backed by one store."""

    def __init__(self, store: SQLiteUserStore, *, session_namespace: str | None = None,
                 ttl: int | float = 86400, clock=time.time):
        if not isinstance(store, SQLiteUserStore):
            raise TypeError("ManagedUsers requires a SQLiteUserStore")
        self.store = store
        namespace = store.instance if session_namespace is None else validate_instance(session_namespace)
        self.instance = store.instance
        self.session_namespace = namespace
        self.sessions = SessionManager(ManagedSessionStore(store), instance=namespace, ttl=ttl, clock=clock)

    @classmethod
    def for_instance(cls, instance: str, *, home=None, max_users: int = MAX_USERS_DEFAULT,
                     max_sessions: int = MAX_SESSIONS_DEFAULT, session_namespace: str | None = None,
                     ttl: int | float = 86400, clock=time.time) -> "ManagedUsers":
        store = SQLiteUserStore.for_instance(instance, home=home, max_users=max_users,
                                             max_sessions=max_sessions)
        return cls(store, session_namespace=session_namespace, ttl=ttl, clock=clock)

    @classmethod
    def in_memory(cls, instance: str, *, max_users: int = MAX_USERS_DEFAULT,
                  max_sessions: int = MAX_SESSIONS_DEFAULT, session_namespace: str | None = None,
                  ttl: int | float = 86400, clock=time.time) -> "ManagedUsers":
        store = SQLiteUserStore.in_memory(instance, max_users=max_users, max_sessions=max_sessions)
        return cls(store, session_namespace=session_namespace, ttl=ttl, clock=clock)

    def close(self) -> None:
        self.store.close()

    def _actor(self, connection: sqlite3.Connection, actor: ManagedPrincipal) -> tuple:
        if not isinstance(actor, ManagedPrincipal) or not actor.authenticated:
            raise ManagedPermissionError("A current managed account is required")
        row = self.store._user_by_id(connection, actor.user_id)
        if (row is None or bool(row[5]) or not bool(row[4])
                or int(row[11]) != actor.auth_revision or row[3] != actor.role.value):
            raise ManagedPermissionError("Managed account is no longer permitted")
        return row

    @staticmethod
    def _live_target(row: tuple | None) -> tuple:
        if row is None or bool(row[5]):
            raise ManagedNotFoundError()
        return row

    @staticmethod
    def _same_actor(actor_row: tuple, target_row: tuple) -> bool:
        return actor_row[0] == target_row[0]

    @staticmethod
    def _owner(row: tuple) -> bool:
        return row[3] == Role.OWNER.value

    def authenticate(self, username: str, password: str) -> ManagedPrincipal | None:
        try:
            username_key = _canonical_username(username)
        except ManagedValidationError:
            return None
        if not _valid_auth_password(password):
            return None
        with self.store._connection() as connection:
            row = self.store._user_by_username(connection, username_key)
        stored = row if row is not None else None
        password_hash = self.store._dummy if stored is None else PasswordHash(
            stored[8], stored[9], int(stored[10])
        )
        verified = verify_pbkdf2(password, password_hash.salt, password_hash.digest,
                                 iterations=password_hash.iterations)
        if (not verified or row is None or bool(row[5]) or not bool(row[4])):
            return None
        return self.store._principal(row)

    def bootstrap_owner(self, username: str, password: str, display_name: str = "") -> UserRecord:
        username_key = _canonical_username(username)
        _validate_new_password(password)
        display_name = _validate_display_name(display_name)
        password_hash = hash_password(password)
        now = _now()
        user_id = uuid.uuid4().hex
        try:
            with self.store._connection(immediate=True) as connection:
                if connection.execute(
                    "SELECT count(*) FROM chatlogin_managed_users WHERE account_instance=?",
                    (self.store.instance,),
                ).fetchone()[0]:
                    raise ManagedConflictError("Managed account directory is not empty")
                connection.execute(
                    "INSERT INTO chatlogin_managed_users "
                    "(account_instance, user_id, username, username_key, display_name, role, enabled, deleted, "
                    "password_salt, password_digest, password_iterations, auth_revision, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, 0, ?, ?)",
                    (self.store.instance, user_id, username_key, username_key, display_name, Role.OWNER.value,
                     password_hash.salt, password_hash.digest, password_hash.iterations, now, now),
                )
                return self.store._record(self.store._user_by_id(connection, user_id))
        except sqlite3.IntegrityError:
            raise ManagedConflictError() from None

    def create_user(self, actor: ManagedPrincipal, username: str, password: str, *,
                    role: Role | str = Role.USER, display_name: str = "") -> UserRecord:
        username_key = _canonical_username(username)
        role = _managed_role(role, creatable=True)
        _validate_new_password(password)
        display_name = _validate_display_name(display_name)
        password_hash = hash_password(password)
        now = _now()
        user_id = uuid.uuid4().hex
        try:
            with self.store._connection(immediate=True) as connection:
                actor_row = self._actor(connection, actor)
                if not (self._owner(actor_row) or (actor_row[3] == Role.ADMIN.value and role is Role.USER)):
                    raise ManagedPermissionError()
                count = connection.execute(
                    "SELECT count(*) FROM chatlogin_managed_users WHERE account_instance=?",
                    (self.store.instance,),
                ).fetchone()[0]
                if count >= self.store.max_users:
                    raise ManagedConflictError("Managed user capacity is exhausted")
                connection.execute(
                    "INSERT INTO chatlogin_managed_users "
                    "(account_instance, user_id, username, username_key, display_name, role, enabled, deleted, "
                    "password_salt, password_digest, password_iterations, auth_revision, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, 0, ?, ?)",
                    (self.store.instance, user_id, username_key, username_key, display_name, role.value,
                     password_hash.salt, password_hash.digest, password_hash.iterations, now, now),
                )
                return self.store._record(self.store._user_by_id(connection, user_id))
        except sqlite3.IntegrityError:
            raise ManagedConflictError() from None

    def current_user(self, actor: ManagedPrincipal) -> UserRecord:
        with self.store._connection() as connection:
            return self.store._record(self._actor(connection, actor))

    def list_users(self, actor: ManagedPrincipal, offset: int = 0, limit: int = 100) -> list[UserRecord]:
        offset, limit = _validate_paging(offset, limit, self.store.max_users)
        with self.store._connection() as connection:
            actor_row = self._actor(connection, actor)
            if self._owner(actor_row):
                rows = connection.execute(
                    f"SELECT {self.store._USER_COLUMNS} FROM chatlogin_managed_users "
                    "WHERE account_instance=? AND deleted=0 ORDER BY created_at, user_id LIMIT ? OFFSET ?",
                    (self.store.instance, limit, offset),
                ).fetchall()
            elif actor_row[3] == Role.ADMIN.value:
                rows = connection.execute(
                    f"SELECT {self.store._USER_COLUMNS} FROM chatlogin_managed_users "
                    "WHERE account_instance=? AND deleted=0 AND (role=? OR user_id=?) "
                    "ORDER BY created_at, user_id LIMIT ? OFFSET ?",
                    (self.store.instance, Role.USER.value, actor_row[0], limit, offset),
                ).fetchall()
            else:
                raise ManagedPermissionError()
        return [self.store._record(row) for row in rows]

    def get_user(self, actor: ManagedPrincipal, user_id: str) -> UserRecord:
        user_id = _validate_user_id(user_id)
        with self.store._connection() as connection:
            actor_row = self._actor(connection, actor)
            target = self._live_target(self.store._user_by_id(connection, user_id))
            if self._same_actor(actor_row, target) or self._owner(actor_row):
                return self.store._record(target)
            if actor_row[3] == Role.ADMIN.value and target[3] == Role.USER.value:
                return self.store._record(target)
            raise ManagedPermissionError()

    def _can_update(self, actor_row: tuple, target: tuple, *, has_display: bool,
                    has_role: bool, has_enabled: bool) -> None:
        if self._owner(target):
            if has_role or has_enabled or not self._same_actor(actor_row, target):
                raise ManagedPermissionError()
            return
        if self._owner(actor_row):
            return
        if actor_row[3] == Role.ADMIN.value:
            if self._same_actor(actor_row, target):
                if has_role or has_enabled:
                    raise ManagedPermissionError()
                return
            if target[3] == Role.USER.value and has_enabled and not has_display and not has_role:
                return
        if (actor_row[3] == Role.USER.value and self._same_actor(actor_row, target)
                and has_display and not has_role and not has_enabled):
            return
        raise ManagedPermissionError()

    def update_user(self, actor: ManagedPrincipal, user_id: str, *, display_name: str | None = None,
                    role: Role | str | None = None, enabled: bool | None = None) -> UserRecord:
        user_id = _validate_user_id(user_id)
        if display_name is None and role is None and enabled is None:
            raise ManagedValidationError("No managed user update was supplied")
        if display_name is not None:
            display_name = _validate_display_name(display_name)
        desired_role = _managed_role(role) if role is not None else None
        if enabled is not None and type(enabled) is not bool:
            raise ManagedValidationError("Enabled status is invalid")
        with self.store._connection(immediate=True) as connection:
            actor_row = self._actor(connection, actor)
            target = self._live_target(self.store._user_by_id(connection, user_id))
            self._can_update(actor_row, target, has_display=display_name is not None,
                             has_role=desired_role is not None, has_enabled=enabled is not None)
            new_display = target[2] if display_name is None else display_name
            new_role = target[3] if desired_role is None else desired_role.value
            new_enabled = int(target[4]) if enabled is None else int(enabled)
            security_changed = new_role != target[3] or new_enabled != int(target[4])
            profile_changed = new_display != target[2]
            if security_changed or profile_changed:
                now = _now()
                if security_changed:
                    connection.execute(
                        "UPDATE chatlogin_managed_users SET display_name=?, role=?, enabled=?, "
                        "auth_revision=auth_revision+1, updated_at=? "
                        "WHERE account_instance=? AND user_id=?",
                        (new_display, new_role, new_enabled, now, self.store.instance, user_id),
                    )
                    self.store._invalidate_sessions(connection, user_id)
                else:
                    connection.execute(
                        "UPDATE chatlogin_managed_users SET display_name=?, updated_at=? "
                        "WHERE account_instance=? AND user_id=?",
                        (new_display, now, self.store.instance, user_id),
                    )
            return self.store._record(self.store._user_by_id(connection, user_id))

    def _can_manage_password(self, actor_row: tuple, target: tuple) -> None:
        if self._owner(target):
            raise ManagedPermissionError()
        if self._owner(actor_row):
            return
        if actor_row[3] == Role.ADMIN.value and target[3] == Role.USER.value:
            return
        raise ManagedPermissionError()

    def reset_password(self, actor: ManagedPrincipal, user_id: str, new_password: str) -> UserRecord:
        user_id = _validate_user_id(user_id)
        _validate_new_password(new_password)
        password_hash = hash_password(new_password)
        with self.store._connection(immediate=True) as connection:
            actor_row = self._actor(connection, actor)
            target = self._live_target(self.store._user_by_id(connection, user_id))
            self._can_manage_password(actor_row, target)
            now = _now()
            connection.execute(
                "UPDATE chatlogin_managed_users SET password_salt=?, password_digest=?, password_iterations=?, "
                "auth_revision=auth_revision+1, updated_at=? WHERE account_instance=? AND user_id=?",
                (password_hash.salt, password_hash.digest, password_hash.iterations, now,
                 self.store.instance, user_id),
            )
            self.store._invalidate_sessions(connection, user_id)
            return self.store._record(self.store._user_by_id(connection, user_id))

    def change_password(self, actor: ManagedPrincipal, current_password: str, new_password: str) -> UserRecord:
        if not _valid_auth_password(current_password):
            raise ManagedValidationError("Password is invalid")
        _validate_new_password(new_password)
        password_hash = hash_password(new_password)
        with self.store._connection(immediate=True) as connection:
            actor_row = self._actor(connection, actor)
            if not verify_pbkdf2(current_password, actor_row[8], actor_row[9], iterations=int(actor_row[10])):
                raise ManagedPermissionError("Current password was not accepted")
            now = _now()
            connection.execute(
                "UPDATE chatlogin_managed_users SET password_salt=?, password_digest=?, password_iterations=?, "
                "auth_revision=auth_revision+1, updated_at=? WHERE account_instance=? AND user_id=?",
                (password_hash.salt, password_hash.digest, password_hash.iterations, now,
                 self.store.instance, actor_row[0]),
            )
            self.store._invalidate_sessions(connection, actor_row[0])
            return self.store._record(self.store._user_by_id(connection, actor_row[0]))

    def delete_user(self, actor: ManagedPrincipal, user_id: str) -> UserRecord:
        user_id = _validate_user_id(user_id)
        with self.store._connection(immediate=True) as connection:
            actor_row = self._actor(connection, actor)
            target = self._live_target(self.store._user_by_id(connection, user_id))
            if self._owner(target):
                raise ManagedPermissionError()
            if not self._owner(actor_row):
                if not (actor_row[3] == Role.ADMIN.value and target[3] == Role.USER.value):
                    raise ManagedPermissionError()
            now = _now()
            connection.execute(
                "UPDATE chatlogin_managed_users SET enabled=0, deleted=1, auth_revision=auth_revision+1, "
                "updated_at=? WHERE account_instance=? AND user_id=?",
                (now, self.store.instance, user_id),
            )
            self.store._invalidate_sessions(connection, user_id)
            return self.store._record(self.store._user_by_id(connection, user_id))

    def transfer_owner(self, actor: ManagedPrincipal, target_user_id: str, current_password: str,
                       confirm_username: str) -> UserRecord:
        target_user_id = _validate_user_id(target_user_id)
        if not isinstance(confirm_username, str) or len(confirm_username) > MAX_USERNAME_BYTES:
            raise ManagedValidationError("Owner confirmation is invalid")
        if not _valid_auth_password(current_password):
            raise ManagedPermissionError("Current password was not accepted")
        with self.store._connection(immediate=True) as connection:
            actor_row = self._actor(connection, actor)
            if not self._owner(actor_row):
                raise ManagedPermissionError()
            target = self._live_target(self.store._user_by_id(connection, target_user_id))
            if self._same_actor(actor_row, target) or self._owner(target) or not bool(target[4]):
                raise ManagedPermissionError()
            if confirm_username != target[1]:
                raise ManagedValidationError("Owner confirmation is invalid")
            if not verify_pbkdf2(current_password, actor_row[8], actor_row[9], iterations=int(actor_row[10])):
                raise ManagedPermissionError("Current password was not accepted")
            now = _now()
            # Demote before promotion so the partial unique owner index is valid at
            # every statement boundary; the transaction keeps the change atomic.
            connection.execute(
                "UPDATE chatlogin_managed_users SET role=?, auth_revision=auth_revision+1, updated_at=? "
                "WHERE account_instance=? AND user_id=?",
                (Role.ADMIN.value, now, self.store.instance, actor_row[0]),
            )
            connection.execute(
                "UPDATE chatlogin_managed_users SET role=?, auth_revision=auth_revision+1, updated_at=? "
                "WHERE account_instance=? AND user_id=?",
                (Role.OWNER.value, now, self.store.instance, target_user_id),
            )
            self.store._invalidate_sessions(connection, actor_row[0])
            self.store._invalidate_sessions(connection, target_user_id)
            return self.store._record(self.store._user_by_id(connection, target_user_id))


__all__ = [
    "ConflictError", "ManagedConflictError", "ManagedError", "ManagedNotFoundError",
    "ManagedPermissionError", "ManagedPrincipal", "ManagedSessionStore", "ManagedUsers",
    "ManagedValidationError", "NotFoundError", "PermissionDenied", "SQLiteUserStore", "UserRecord",
    "ValidationError",
]
