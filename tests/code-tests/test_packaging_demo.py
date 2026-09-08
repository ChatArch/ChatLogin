"""Source-distribution and executable-example contracts."""
from pathlib import Path
import runpy

import pytest
from fastapi.testclient import TestClient

from chatlogin import CallbackBackend, Principal, __version__

ROOT = Path(__file__).resolve().parents[2]


def test_sdist_carries_examples_and_full_regression_sources():
    manifest = ROOT / "MANIFEST.in"
    assert manifest.is_file(), "Source distributions must include full tests/docs/examples"
    text = manifest.read_text()
    for entry in ("recursive-include tests *.py *.md", "recursive-include examples *.py", "recursive-include docs *.md", "include README.en.md CHANGELOG.md DEVELOP.md"):
        assert entry in text


def demo_factory():
    namespace = runpy.run_path(str(ROOT / "examples/demo_fastapi.py"))
    assert callable(namespace.get("create_app")), "Example must expose an explicit factory"
    return namespace["create_app"]


def test_example_has_no_default_credentials(monkeypatch):
    monkeypatch.delenv("CHATLOGIN_DEMO_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="CHATLOGIN_DEMO_PASSWORD"):
        demo_factory()()


def test_example_has_real_host_routes_and_injected_credentials():
    backend = CallbackBackend(lambda account, password: Principal("demo-user", "Demo") if (account, password) == ("demo", "fixture-only-password") else None)
    app = demo_factory()(backend=backend, origin="http://testserver")
    with TestClient(app) as client:
        assert client.get("/health").json()["version"] == __version__
        assert "Guest" in client.get("/").text
        assert client.get("/private").status_code == 401
        response = client.post("/api/auth/login", headers={"Origin": "http://testserver"}, json={"username": "demo", "password": "fixture-only-password"})
        assert response.status_code == 200
        assert "Demo" in client.get("/").text
        assert client.get("/private").json()["user_id"] == "demo-user"
        assert 'id="logout"' in client.get("/").text
        assert client.get("/demo.js").status_code == 200
        assert client.get("/docs").status_code == 404
