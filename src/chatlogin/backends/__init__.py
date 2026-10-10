"""Opt-in, host-schema compatibility backends; no web dependencies required."""
from .chatvoice import ChatVoiceAuth, ChatVoiceSessionStore
from .chatvoice_managed import ChatVoiceManagedStore, adopt_owner, initialize_chatvoice_managed_schema

__all__ = [
    "ChatVoiceAuth", "ChatVoiceManagedStore", "ChatVoiceSessionStore",
    "adopt_owner", "initialize_chatvoice_managed_schema",
]
