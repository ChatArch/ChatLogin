"""ChatEnv extension point for ChatLogin; no login configuration yet."""

from chatenv import BaseEnvConfig


class ChatLoginConfig(BaseEnvConfig):
    """Namespace reserved for future, explicitly defined login settings."""

    _title = "ChatLogin Configuration"
    _aliases = ["chatlogin"]
    _storage_dir = "ChatLogin"

    @classmethod
    def test(cls) -> None:
        """Validate schema registration without network or storage writes."""
        print("ChatLogin schema loaded; login features are not implemented yet.")


__all__ = ["ChatLoginConfig"]
