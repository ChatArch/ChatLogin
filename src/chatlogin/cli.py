"""CLI entrypoint for chatlogin."""

from __future__ import annotations

import click
import json
import ipaddress
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


def _loopback_origin(host: str, port: int) -> str:
    if host == "localhost":
        authority = host
    else:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise click.ClickException("--origin is required unless --host is an explicit loopback address") from exc
        if not address.is_loopback:
            raise click.ClickException("--origin is required unless --host is an explicit loopback address")
        authority = f"[{host}]" if address.version == 6 else host
    return f"http://{authority}:{port}"


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address; loopback by default.")
@click.option("--port", default=8765, show_default=True, type=click.IntRange(1, 65535), help="TCP port.")
@click.option("--origin", help="Fixed trusted public origin for browser Host/Origin checks.")
def serve_command(host: str, port: int, origin: str | None) -> None:
    """Serve the isolated synthetic product demonstration."""
    trusted_origin = origin or _loopback_origin(host, port)
    try:
        import uvicorn
        from chatlogin.demo import create_demo_app
    except ModuleNotFoundError as exc:
        raise click.ClickException(
            'Demo dependencies are missing. Install them with: pip install "ChatLogin[demo]"'
        ) from exc
    try:
        app = create_demo_app(origin=trusted_origin)
    except ValueError as exc:
        raise click.ClickException(f"Invalid --origin: {exc}") from exc
    click.echo(f"ChatLogin demo: {trusted_origin}")
    # Never infer the public origin from proxy-supplied headers.
    uvicorn.run(app, host=host, port=port, proxy_headers=False, forwarded_allow_ips="", access_log=False)


if __name__ == "__main__":
    main()
