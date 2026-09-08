"""CSRF, conservative local redirects and a bounded per-process limiter."""
import hmac
import math
import threading
import time
from urllib.parse import unquote
from typing import Callable

from .identity import AccessDenied


def require_csrf(session, submitted: str | None) -> None:
    if (not isinstance(submitted, str) or not submitted or len(submitted) > 1024
            or not hmac.compare_digest(session.csrf_token.encode(), submitted.encode("utf-8", "replace"))):
        raise AccessDenied(403, "CSRF validation failed")


def _local(value: str) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    for _ in range(5):
        if (not value.startswith("/") or value.startswith("//") or "\\" in value
                or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            return False
        decoded = unquote(value)
        if decoded == value:
            return True
        value = decoded
    return False


def safe_next(value: str | None, default: str = "/") -> str:
    """Return an absolute local path, or a validated local fallback.

    Deliberately rejects encoded controls, backslashes and nested encodings.
    """
    if not _local(default):
        raise ValueError("Default redirect must be a safe local path")
    return value if _local(value) else default


class LoginRateLimiter:
    """Thread-safe fixed windows. Reject new keys when full; never evict live keys.

    A process-local backstop, not a distributed abuse-prevention service.
    """
    def __init__(self, *, limit: int = 10, window: float = 60, max_keys: int = 1024,
                 clock: Callable[[], float] = time.monotonic):
        if limit < 1 or max_keys < 1 or not math.isfinite(window) or window <= 0:
            raise ValueError("Invalid rate limit")
        self.limit, self.window, self.max_keys = limit, window, max_keys
        self._clock = clock
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            now = self._clock()
            self._buckets = {k: v for k, v in self._buckets.items() if now < v[0] + self.window}
            start, count = self._buckets.get(key, (now, 0))
            if count >= self.limit or (key not in self._buckets and len(self._buckets) >= self.max_keys):
                return False
            self._buckets[key] = (start, count + 1)
            return True
