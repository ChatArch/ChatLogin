"""Managed-users CLI surface that remains inspectable without optional Web imports."""

from click.testing import CliRunner

from chatlogin.cli import main


def test_users_bootstrap_is_discoverable_with_safe_credential_input():
    runner = CliRunner()

    result = runner.invoke(main, ["users", "bootstrap", "--help"])

    assert result.exit_code == 0, result.output
    assert "USERNAME" in result.output
    assert "--instance" in result.output
    assert "--password-env" in result.output
    assert "--display-name" in result.output
    assert "--home" in result.output
    assert "--json" in result.output
    assert "-i, --interactive" in result.output
    assert "--password TEXT" not in result.output


def test_users_and_managed_demo_appear_in_registered_tree_without_optional_imports():
    runner = CliRunner()

    serve_help = runner.invoke(main, ["serve", "--help"])
    tree = runner.invoke(main, ["--tree"])
    brief_tree = runner.invoke(main, ["--tree-brief"])

    assert serve_help.exit_code == 0, serve_help.output
    assert "--managed-demo" in serve_help.output
    for result in (tree, brief_tree):
        assert result.exit_code == 0, result.output
        assert "users" in result.output
        assert "bootstrap" in result.output
        assert "serve" in result.output


def test_bootstrap_rejects_a_missing_credential_environment_before_core_initialization(tmp_path):
    runner = CliRunner()
    home = tmp_path / "absent-home"

    result = runner.invoke(
        main,
        [
            "users", "bootstrap", "operator",
            "--instance", "my-site",
            "--password-env", "APP_BOOTSTRAP_CREDENTIAL",
            "--home", str(home),
        ],
        env={"APP_BOOTSTRAP_CREDENTIAL": ""},
    )

    assert result.exit_code != 0
    assert "missing or empty" in result.output
    assert not home.exists()


def test_bootstrap_noninteractive_mode_fails_without_prompting_for_missing_operator_input():
    result = CliRunner().invoke(main, ["users", "bootstrap", "-I"])

    assert result.exit_code != 0
    assert "Missing required value: username" in result.output
