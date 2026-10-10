"""Managed demo wiring contracts; integration tests activate after Core and Web land."""

from importlib.util import find_spec

import pytest


def _managed_stack_is_available() -> bool:
    return find_spec("chatlogin.managed") is not None and find_spec("chatlogin.managed_web") is not None


def test_managed_demo_factory_is_importable_without_materializing_optional_web_stack():
    from chatlogin.managed_demo import create_managed_demo_app

    assert callable(create_managed_demo_app)


@pytest.mark.skipif(not _managed_stack_is_available(), reason="awaiting managed Core and Web integration")
def test_managed_demo_exposes_only_public_synthetic_fixture_metadata():
    from fastapi.testclient import TestClient

    from chatlogin import __version__
    from chatlogin.managed_demo import create_managed_demo_app

    with TestClient(create_managed_demo_app(origin="https://managed-demo.test"), base_url="https://managed-demo.test") as client:
        assert client.get("/health").json() == {
            "version": __version__,
            "mode": "managed-demo",
            "synthetic": True,
        }
        fixtures = client.get("/api/managed-demo/accounts")
        assert fixtures.headers["cache-control"] == "no-store"
        assert fixtures.json()["synthetic"] is True
        assert {row["role"] for row in fixtures.json()["accounts"]} == {"owner", "admin", "user"}
