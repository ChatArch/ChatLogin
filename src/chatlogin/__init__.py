"""ChatLogin reusable authentication. Web dependencies are imported only on demand."""
from .credentials import (
    AsyncCallbackBackend,
    AsyncCredentialBackend,
    CallbackBackend,
    CredentialBackend,
    PasswordBackend,
    PasswordHash,
    hash_password,
    verify_pbkdf2,
)
from .identity import AccessDenied, Principal, Role, require_owner, require_role, require_user
from .paths import StatePaths, state_paths
from .private_sqlite import PrivateSQLite
from .security import LoginRateLimiter, require_csrf, safe_next
from .sessions import IssuedSession, MemorySessionStore, Session, SessionManager, SessionStore, StoreFull
from .sqlite import SQLiteSessionStore

__version__ = "0.1.5"
__all__ = [
    "__version__", "AccessDenied", "Principal", "Role", "require_owner", "require_role", "require_user",
    "AsyncCallbackBackend", "AsyncCredentialBackend", "CallbackBackend", "CredentialBackend",
    "PasswordBackend", "PasswordHash", "hash_password", "verify_pbkdf2",
    "StatePaths", "state_paths", "LoginRateLimiter", "require_csrf", "safe_next", "IssuedSession",
    "MemorySessionStore", "PrivateSQLite", "Session", "SessionManager", "SessionStore", "StoreFull",
    "SQLiteSessionStore",
]
