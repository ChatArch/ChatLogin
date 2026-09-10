"""Opt-in, host-schema compatibility backends; no web dependencies required."""
from .chatvoice import ChatVoiceAuth, ChatVoiceSessionStore

__all__ = ["ChatVoiceAuth", "ChatVoiceSessionStore"]
