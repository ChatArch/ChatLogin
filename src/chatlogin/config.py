"""ChatEnv extension point for ChatLogin; runtime auth settings stay explicit."""

from chatenv import BaseEnvConfig


class ChatLoginConfig(BaseEnvConfig):
    """Namespace reserved for future, explicitly defined login settings."""

    _title = "ChatLogin Configuration"
    _aliases = ["chatlogin"]
    _storage_dir = "ChatLogin"

    @classmethod
    def test(cls) -> None:
        """Validate schema registration without network or storage writes."""
        print("ChatLogin schema loaded; configure auth explicitly through its factory.")


__all__ = ["ChatLoginConfig"]
