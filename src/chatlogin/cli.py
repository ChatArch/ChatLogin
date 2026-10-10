"""CLI entrypoint for chatlogin."""

from __future__ import annotations

import click
import json
import ipaddress
import os
import re
from chatstyle import CommandField, CommandSchema, add_interactive_option, add_tree_option, resolve_command_inputs

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


@main.group("users")
def users_group() -> None:
    """Explicit managed-user lifecycle operations."""


_BOOTSTRAP_SCHEMA = CommandSchema(
    "users bootstrap",
    fields=(
        CommandField("username", "Owner username", required=True, prompt_if_missing=True),
        CommandField("instance", "Managed account instance name", required=True, prompt_if_missing=True),
        CommandField(
            "password_env",
            "Environment variable holding the bootstrap password",
            required=True,
            prompt_if_missing=True,
        ),
        CommandField("display_name", "Owner display name", default=""),
        CommandField("home", "Explicit ChatArch home", default=None),
    ),
)


def _managed_record_payload(record) -> dict[str, object]:
    """Render the documented safe record view without inspecting store internals."""
    role = getattr(record, "role")
    return {
        "user_id": getattr(record, "user_id"),
        "username": getattr(record, "username"),
        "display_name": getattr(record, "display_name"),
        "role": getattr(role, "value", role),
        "enabled": getattr(record, "enabled"),
        "deleted": getattr(record, "deleted"),
        "created_at": str(getattr(record, "created_at")),
        "updated_at": str(getattr(record, "updated_at")),
    }


@users_group.command("bootstrap")
@add_interactive_option
@click.argument("username", required=False)
@click.option("--instance", metavar="NAME", help="Managed account instance name.")
@click.option("--password-env", metavar="KEY", help="Environment variable holding the bootstrap password.")
@click.option("--display-name", default="", show_default=False, help="Optional owner display name.")
@click.option("--home", type=click.Path(path_type=str), help="Explicit ChatArch home (overrides ChatEnv default).")
@click.option("--json", "as_json", is_flag=True, help="Print the safe owner record as JSON.")
def users_bootstrap_command(
    username: str | None,
    instance: str | None,
    password_env: str | None,
    display_name: str,
    home: str | None,
    as_json: bool,
    interactive: bool | None,
) -> None:
    """Create the first owner in an explicitly empty managed-user instance."""
    values = resolve_command_inputs(
        schema=_BOOTSTRAP_SCHEMA,
        provided={
            "username": username,
            "instance": instance,
            "password_env": password_env,
            "display_name": display_name,
            "home": home,
        },
        interactive=interactive,
        usage="chatlogin users bootstrap USERNAME --instance NAME --password-env KEY",
    )
    username = values["username"]
    instance = values["instance"]
    password_env = values["password_env"]
    display_name = values["display_name"]
    home = values["home"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", password_env):
        raise click.ClickException("--password-env must name a valid environment variable")
    try:
        # This read-only path validation runs before the store can initialize.
        state_paths(instance, home=home)
    except (ValueError, TypeError) as exc:
        raise click.ClickException(str(exc)) from exc
    password = os.environ.get(password_env)
    if not password:
        raise click.ClickException(f"Environment variable {password_env!r} is missing or empty")
    try:
        from chatlogin.managed import ManagedUsers
        users = ManagedUsers.for_instance(instance, home=home)
        record = users.bootstrap_owner(username, password, display_name=display_name)
    except Exception as exc:
        # Do not echo exception content: it can originate in an operator-provided
        # credential or in a filesystem path. The Core enforces the actual policy.
        raise click.ClickException(
            "Managed owner bootstrap was not completed. Verify an empty instance and a safe state path."
        ) from exc
    payload = _managed_record_payload(record)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False))
    else:
        click.echo(f"Bootstrapped managed owner: {payload['username']} ({payload['role']})")


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
@click.option("--managed-demo", is_flag=True, help="Serve the disposable managed-users demonstration.")
def serve_command(host: str, port: int, origin: str | None, managed_demo: bool) -> None:
    """Serve the isolated synthetic product demonstration."""
    trusted_origin = origin or _loopback_origin(host, port)
    try:
        import uvicorn
        if managed_demo:
            from chatlogin.managed_demo import create_managed_demo_app
            factory = create_managed_demo_app
        else:
            from chatlogin.demo import create_demo_app
            factory = create_demo_app
    except ModuleNotFoundError as exc:
        raise click.ClickException(
            'Demo dependencies are missing. Install them with: pip install "ChatLogin[demo]"'
        ) from exc
    try:
        app = factory(origin=trusted_origin)
    except (RuntimeError, ValueError) as exc:
        raise click.ClickException(f"Invalid --origin: {exc}") from exc
    label = "ChatLogin managed demo" if managed_demo else "ChatLogin demo"
    click.echo(f"{label}: {trusted_origin}")
    # Never infer the public origin from proxy-supplied headers.
    uvicorn.run(app, host=host, port=port, proxy_headers=False, forwarded_allow_ips="", access_log=False)


if __name__ == "__main__":
    main()
