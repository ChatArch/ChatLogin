"""Injectable credential verification; host databases stay authoritative."""
from dataclasses import dataclass, field
import hashlib
import hmac
import secrets
from typing import Callable, Mapping, Protocol

from .identity import Principal

MAX_PASSWORD_BYTES = 1024
MAX_USERNAME_BYTES = 256


def valid_credentials(username: str, password: str) -> bool:
    try:
        return (isinstance(username, str) and isinstance(password, str)
                and 0 < len(username.encode("utf-8")) <= MAX_USERNAME_BYTES
                and 0 < len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES)
    except UnicodeError:
        return False


@dataclass(frozen=True)
class PasswordHash:
    salt: bytes = field(repr=False)
    digest: bytes = field(repr=False)
    iterations: int = 600_000

    def __post_init__(self):
        if (not isinstance(self.salt, bytes) or not 16 <= len(self.salt) <= 1024
                or not isinstance(self.digest, bytes) or len(self.digest) != 32
                or type(self.iterations) is not int or not 1 <= self.iterations <= 10_000_000):
            raise ValueError("Invalid trusted PasswordHash configuration")


def hash_password(password: str) -> PasswordHash:
    if not valid_credentials("account", password):
        raise ValueError("Password must be 1..1024 UTF-8 bytes")
    salt = secrets.token_bytes(16)
    return PasswordHash(salt, hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000))


def verify_pbkdf2(password: str, salt: bytes, digest: bytes, *, iterations: int = 310_000) -> bool:
    """Verify existing SHA256 PBKDF2 BLOBs without changing the host format.

    Parameters are trusted server-side material, never read from a login body.
    """
    if not valid_credentials("account", password):
        return False
    if type(iterations) is not int or not 1 <= iterations <= 10_000_000:
        raise ValueError("Invalid trusted PBKDF2 iteration count")
    if not isinstance(salt, bytes) or not isinstance(digest, bytes) or len(digest) != 32:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return hmac.compare_digest(actual, digest)


class CredentialBackend(Protocol):
    def authenticate(self, username: str, password: str) -> Principal | None: ...


def _checked(principal: Principal | None) -> Principal | None:
    if principal is not None and (not isinstance(principal, Principal) or not principal.authenticated):
        raise ValueError("Backend must return a trusted authenticated Principal or None")
    return principal


class CallbackBackend:
    def __init__(self, authenticate: Callable[[str, str], Principal | None]):
        self._authenticate = authenticate

    def authenticate(self, username: str, password: str) -> Principal | None:
        if not valid_credentials(username, password):
            return None
        return _checked(self._authenticate(username, password))


class PasswordBackend:
    """One entry is fixed-account mode; multiple entries are multi-account mode.

    Keys are exact usernames; host normalization belongs in a CallbackBackend.
    Only password hashes are retained. No accounts are created by default.
    """
    def __init__(self, accounts: Mapping[str, tuple[Principal, PasswordHash]]):
        if not accounts:
            raise ValueError("At least one explicitly configured account is required")
        self._accounts = dict(accounts)
        for username, (principal, password) in self._accounts.items():
            if not valid_credentials(username, "check") or not isinstance(password, PasswordHash):
                raise ValueError("Invalid account configuration")
            if _checked(principal) is None:
                raise ValueError("Configured accounts require an authenticated Principal")
        self._dummy = PasswordHash(secrets.token_bytes(16), secrets.token_bytes(32))

    def authenticate(self, username: str, password: str) -> Principal | None:
        if not valid_credentials(username, password):
            return None
        account = self._accounts.get(username)
        stored = account[1] if account else self._dummy
        verified = verify_pbkdf2(password, stored.salt, stored.digest, iterations=stored.iterations)
        return account[0] if account and verified else None
