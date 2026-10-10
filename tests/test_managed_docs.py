"""Documentation promises for the managed-users adoption path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_bilingual_managed_users_guides_cover_adoption_and_boundaries():
    zh = _read("docs/managed-users.md")
    en = _read("docs/managed-users.en.md")

    for text in (zh, en):
        assert "create_managed_auth" in text
        assert "ManagedUsers.for_instance" in text
        assert "ManagedUsers.in_memory" in text
        assert "require_owner" in text
        assert "SSO" in text and "OAuth" in text and "MFA" in text
        assert "ChatLogin>=0.2.0,<0.3.0" in text
        assert "bootstrap" in text
        assert "managed-demo" in text


def test_indexes_cli_tree_and_navigation_link_the_managed_path():
    for name in ("README.md", "README.en.md", "docs/index.md", "docs/index.en.md", "docs/cli-tree.md", "docs/cli-tree.en.md", "mkdocs.yml"):
        assert "managed" in _read(name).lower(), name

    navigation = _read("mkdocs.yml")
    assert "Managed Users" in navigation
    assert "托管用户" in navigation
