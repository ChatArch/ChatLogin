"""Opaque sessions and injectable, namespace-aware storage contracts."""
from dataclasses import dataclass, field
import hashlib
import math
import re
import secrets
import threading
import time
from typing import Callable, Protocol

from .identity import Principal, require_user
from .paths import validate_instance


@dataclass(frozen=True)
class Session:
    principal: Principal
    expires_at: float
    csrf_token: str = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.principal, Principal) or not self.principal.authenticated:
            raise ValueError("Session requires an authenticated Principal")
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at):
            raise ValueError("Session expiry must be a finite number")
        if (not isinstance(self.csrf_token, str) or not 32 <= len(self.csrf_token) <= 1024
                or not re.fullmatch(r"[A-Za-z0-9_-]+", self.csrf_token)):
            raise ValueError("Session CSRF must be 32..1024 URL-safe ASCII characters")


@dataclass(frozen=True)
class IssuedSession:
    token: str = field(repr=False)
    session: Session


class StoreFull(Exception):
    """Store capacity is exhausted; fail closed without evicting live sessions."""


class SessionStore(Protocol):
    """Implementations must namespace EVERY operation and make put/replace atomic.

    Only SHA256 hex token digests cross this boundary. CSRF is a separate secret.
    purge_expired must not remove another namespace's records.
    """
    def put(self, instance: str, digest: str, session: Session, *, previous_digest: str | None = None) -> None: ...
    def get(self, instance: str, digest: str) -> Session | None: ...
    def delete(self, instance: str, digest: str) -> None: ...
    def purge_expired(self, instance: str, now: float) -> None: ...


class MemorySessionStore:
    """Global capacity across instances; not durable or shared between processes."""
    def __init__(self, *, max_sessions: int = 1024):
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be positive")
        self.max_sessions = max_sessions
        self._sessions: dict[tuple[str, str], Session] = {}
        self._lock = threading.Lock()

    def put(self, instance, digest, session, *, previous_digest=None):
        if not isinstance(session, Session):
            raise ValueError("Session store requires a validated Session")
        with self._lock:
            if (instance, digest) in self._sessions:
                raise ValueError("Session digest already exists")
            old = (instance, previous_digest)
            replaces = old in self._sessions
            if len(self._sessions) >= self.max_sessions and not replaces:
                raise StoreFull("Session capacity exhausted")
            if replaces:
                del self._sessions[old]
            self._sessions[(instance, digest)] = session

    def get(self, instance, digest):
        with self._lock:
            return self._sessions.get((instance, digest))

    def delete(self, instance, digest):
        with self._lock:
            self._sessions.pop((instance, digest), None)

    def purge_expired(self, instance, now):
        with self._lock:
            self._sessions = {k: v for k, v in self._sessions.items()
                              if k[0] != instance or v.expires_at > now}


class SessionManager:
    def __init__(self, store: SessionStore, *, instance: str, ttl: int = 86400,
                 clock: Callable[[], float] = time.time):
        self.instance = validate_instance(instance)
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("Session TTL must be positive and finite")
        self.store, self.ttl, self._clock = store, ttl, clock

    def _now(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError("Session clock must return a finite number")
        return now

    @staticmethod
    def digest(token: str | None) -> str | None:
        # Accept existing host opaque formats, not only newly issued URL-safe tokens.
        if not isinstance(token, str) or not 16 <= len(token) <= 1024:
            return None
        try:
            return hashlib.sha256(token.encode("utf-8")).hexdigest()
        except UnicodeError:
            return None

    def issue(self, principal: Principal, *, previous_token: str | None = None) -> IssuedSession:
        require_user(principal)
        now = self._now()
        token = secrets.token_urlsafe(32)
        session = Session(principal, now + self.ttl, secrets.token_urlsafe(32))
        self.store.purge_expired(self.instance, now)
        self.store.put(self.instance, self.digest(token), session,
                       previous_digest=self.digest(previous_token))
        return IssuedSession(token, session)

    def resolve(self, token: str | None) -> Session | None:
        digest = self.digest(token)
        if digest is None:
            return None
        session = self.store.get(self.instance, digest)
        if session is not None and session.expires_at <= self._now():
            self.store.delete(self.instance, digest)
            return None
        return session

    def revoke(self, token: str | None) -> None:
        digest = self.digest(token)
        if digest is not None:
            self.store.delete(self.instance, digest)
