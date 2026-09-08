from click.testing import CliRunner

from chatlogin import __version__
from chatlogin.cli import main


def test_version_option_reports_package_version():
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert f"chatlogin, version {__version__}" in result.output


def test_help_lists_shared_tree_options():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "--tree" in result.output
    assert "--tree-brief" in result.output


def test_tree_option_prints_registered_cli_tree():
    result = CliRunner().invoke(main, ["--tree"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("chatlogin\n")
    assert "├── --help" in result.output
    assert "├── --version" in result.output
    assert "├── --tree" in result.output
    assert "├── --tree-brief" in result.output


def test_tree_brief_option_prints_registered_cli_tree():
    result = CliRunner().invoke(main, ["--tree-brief"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("chatlogin\n")
    assert "├── --tree" in result.output
    assert "├── --tree-brief" in result.output
