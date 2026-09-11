"""Public session purge delegates through validated SessionManager state."""
import pytest

import chatlogin as cl


def people():
    return cl.Principal("alpha-user"), cl.Principal("beta-user")


@pytest.mark.parametrize("store_factory", [
    lambda tmp_path: cl.MemorySessionStore(),
    lambda tmp_path: cl.SQLiteSessionStore(tmp_path / "sessions.sqlite3"),
])
def test_purge_expired_is_public_namespaced_and_keeps_live_sessions(tmp_path, store_factory):
    now = [100.0]
    store = store_factory(tmp_path)
    alpha = cl.SessionManager(store, instance="alpha", ttl=10, clock=lambda: now[0])
    beta = cl.SessionManager(store, instance="beta", ttl=10, clock=lambda: now[0])
    alpha_user, beta_user = people()
    alpha_old = alpha.issue(alpha_user)
    beta_old = beta.issue(beta_user)
    now[0] = 105.0
    alpha_live = alpha.issue(alpha_user)
    beta_live = beta.issue(beta_user)

    now[0] = 111.0
    alpha.purge_expired()

    assert alpha.resolve(alpha_old.token) is None
    assert alpha.resolve(alpha_live.token).principal == alpha_user
    assert store.get("beta", beta.digest(beta_old.token)).principal == beta_user
    assert beta.resolve(beta_live.token).principal == beta_user
    assert beta.resolve(beta_old.token) is None


def test_purge_expired_validates_clock_and_instance_before_store_call():
    calls = []

    class Store:
        def purge_expired(self, instance, now):
            calls.append((instance, now))

        def put(self, instance, digest, session, *, previous_digest=None):
            raise AssertionError("not used")

        def get(self, instance, digest):
            raise AssertionError("not used")

        def delete(self, instance, digest):
            raise AssertionError("not used")

    manager = cl.SessionManager(Store(), instance="valid-name", clock=lambda: float("nan"))
    with pytest.raises(ValueError):
        manager.purge_expired()
    assert calls == []
