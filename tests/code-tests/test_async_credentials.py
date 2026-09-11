"""Async credential backends match the synchronous validation contract."""
import asyncio

import pytest

import chatlogin as cl


def run(coro):
    return asyncio.run(coro)


def test_async_callback_authenticates_principal_and_none():
    calls = []
    user = cl.Principal("async-user", "Async User")

    async def authenticate(username, password):
        calls.append((username, password))
        return user if (username, password) == ("alice", "correct-password") else None

    backend = cl.AsyncCallbackBackend(authenticate)
    assert run(backend.authenticate("alice", "correct-password")) == user
    assert run(backend.authenticate("alice", "wrong-password")) is None
    assert calls == [("alice", "correct-password"), ("alice", "wrong-password")]


def test_async_callback_rejects_bad_shapes_without_calling_callback():
    calls = []

    async def authenticate(username, password):
        calls.append((username, password))
        return cl.Principal("should-not-run")

    backend = cl.AsyncCallbackBackend(authenticate)
    assert run(backend.authenticate("", "password")) is None
    assert run(backend.authenticate("alice", "")) is None
    assert run(backend.authenticate("x" * 257, "password")) is None
    assert run(backend.authenticate("alice", "x" * 1025)) is None
    assert calls == []


@pytest.mark.parametrize("result", [cl.Principal.guest(), object(), "user"])
def test_async_callback_invalid_results_fail_closed(result):
    async def authenticate(username, password):
        return result

    with pytest.raises(ValueError):
        run(cl.AsyncCallbackBackend(authenticate).authenticate("alice", "password"))


def test_async_callback_requires_awaitable_result():
    backend = cl.AsyncCallbackBackend(lambda username, password: cl.Principal("sync-user"))
    with pytest.raises(TypeError):
        run(backend.authenticate("alice", "password"))


def test_async_backend_public_protocol_exported():
    class Backend:
        async def authenticate(self, username, password):
            return cl.Principal("protocol-user")

    backend: cl.AsyncCredentialBackend = Backend()
    assert run(backend.authenticate("alice", "password")).user_id == "protocol-user"
