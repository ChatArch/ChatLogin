"""Trusted identity and explicit authorization; no business-data bypass."""
from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    GUEST = "guest"
    USER = "user"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    display_name: str = ""
    role: Role = Role.USER

    def __post_init__(self):
        object.__setattr__(self, "role", Role(self.role))
        if self.role is Role.GUEST:
            if self.user_id is not None:
                raise ValueError("Guest cannot have an account identity")
        elif not isinstance(self.user_id, str) or not self.user_id or len(self.user_id) > 256:
            raise ValueError("Authenticated identity requires a bounded nonempty user_id")
        if not isinstance(self.display_name, str) or len(self.display_name) > 256:
            raise ValueError("Invalid display_name")

    @property
    def authenticated(self) -> bool:
        return self.role is not Role.GUEST

    @classmethod
    def guest(cls) -> "Principal":
        return cls(None, "", Role.GUEST)

    def as_dict(self) -> dict:
        return {"user_id": self.user_id, "display_name": self.display_name, "role": self.role.value}


class AccessDenied(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def require_user(principal: Principal) -> Principal:
    if not principal.authenticated:
        raise AccessDenied(401, "Authentication required")
    return principal


def require_role(principal: Principal, *roles: Role) -> Principal:
    require_user(principal)
    if principal.role not in roles:
        raise AccessDenied(403, "Role not permitted")
    return principal


def require_owner(principal: Principal, owner_id: str) -> Principal:
    require_user(principal)
    if principal.user_id != owner_id:
        raise AccessDenied(403, "Resource not permitted")
    return principal
