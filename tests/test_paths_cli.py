"""Paths API and CLI are read-only views of the same ChatEnv home."""
import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
import pytest
import chatlogin as cl
from chatlogin.cli import main


def test_explicit_home_wins_and_expands_user(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "ignored"))
    import chatenv
    def forbidden():
        raise AssertionError("explicit home must not consult default profiles")
    monkeypatch.setattr(chatenv, "get_paths", forbidden)
    assert cl.state_paths("alpha", home="~/chosen").directory == tmp_path / "chosen/chatlogin/instances/alpha"
    assert not (tmp_path / "chosen").exists()


def test_default_home_delegates_to_chatenv(tmp_path, monkeypatch):
    import chatenv
    monkeypatch.setattr(chatenv, "get_paths", lambda: SimpleNamespace(home_dir=tmp_path / "profile-home"))
    assert cl.state_paths("alpha").directory == tmp_path / "profile-home/chatlogin/instances/alpha"
    assert not (tmp_path / "profile-home").exists()


@pytest.mark.parametrize("home", ["$CHATLOGIN_UNKNOWN/home", "${CHATLOGIN_UNKNOWN}/home"])
def test_unknown_home_variables_rejected_before_creation(home, monkeypatch):
    monkeypatch.delenv("CHATLOGIN_UNKNOWN", raising=False)
    with pytest.raises(ValueError):
        cl.state_paths("alpha", home=home)
    with pytest.raises(ValueError):
        cl.SQLiteSessionStore.for_instance("alpha", home=home)


@pytest.mark.parametrize("instance", ["../escape", "a/b", "..", "a\\b", "x" * 65])
def test_invalid_instance_rejected_before_creation(instance, tmp_path):
    home = tmp_path / "absent"
    with pytest.raises(ValueError):
        cl.SQLiteSessionStore.for_instance(instance, home=home)
    assert not home.exists()


def test_paths_cli_json_and_text_are_read_only(tmp_path):
    home = tmp_path / "absent"
    expected = cl.state_paths("alpha", home=home)
    result = CliRunner().invoke(main, ["paths", "alpha", "--home", str(home), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"directory": str(expected.directory), "database": str(expected.database)}
    text = CliRunner().invoke(main, ["paths", "alpha", "--home", str(home)])
    assert text.exit_code == 0
    assert str(expected.directory) in text.output and str(expected.database) in text.output
    assert not home.exists()


@pytest.mark.parametrize("option", ["--tree", "--tree-brief"])
def test_shared_cli_tree_contains_real_paths_command(option):
    result = CliRunner().invoke(main, [option])
    assert result.exit_code == 0, result.output
    assert "paths" in result.output


def test_invalid_paths_cli_is_clean_failure(tmp_path):
    result = CliRunner().invoke(main, ["paths", "../escape", "--home", str(tmp_path / "absent"), "--json"])
    assert result.exit_code != 0
    assert "Instance" in result.output
    assert not (tmp_path / "absent").exists()
