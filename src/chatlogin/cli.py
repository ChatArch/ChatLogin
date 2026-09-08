"""CLI entrypoint for chatlogin."""

from __future__ import annotations

import click
import json
from chatstyle import add_tree_option

from chatlogin import __version__
from chatlogin.paths import state_paths


@click.group(name="chatlogin", invoke_without_command=True, no_args_is_help=True)
@click.version_option(__version__, prog_name="chatlogin")
@add_tree_option(renderer_options={"root_name": "chatlogin"})
def main() -> None:
    """chatlogin command line interface."""
    pass


@main.command("paths")
@click.argument("instance")
@click.option("--home", type=click.Path(path_type=str), help="Explicit ChatArch home (overrides ChatEnv default).")
@click.option("--json", "as_json", is_flag=True, help="Print paths as JSON.")
def paths_command(instance: str, home: str | None, as_json: bool) -> None:
    """Show instance runtime paths without creating files or directories."""
    try:
        paths = state_paths(instance, home=home)
    except (ValueError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    values = {"directory": str(paths.directory), "database": str(paths.database)}
    if as_json:
        click.echo(json.dumps(values))
    else:
        for name, value in values.items():
            click.echo(f"{name}: {value}")


if __name__ == "__main__":
    main()
