# CLI Tree

Reusable authentication and web behavior are [Python APIs](interface-tree.md). The CLI can also run the isolated product demo; it is not a production login service.

## Top-Level Commands

```text
chatlogin
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── paths <INSTANCE> [--home HOME] [--json]  # Show instance runtime paths without creating files or directories.
├── serve [--host HOST] [--port PORT] [--origin ORIGIN] [--managed-demo]  # Serve the isolated synthetic product demonstration.
└── users  # Explicit managed-user lifecycle operations.
    └── bootstrap [--interactive] [USERNAME] [--instance INSTANCE] [--password-env PASSWORD-ENV] [--display-name DISPLAY-NAME] [--home HOME] [--json]  # Create the first owner in an explicitly empty managed-user instance.
```

## Path Inspection

```bash
chatlogin paths my-site --json
chatlogin paths my-site --home "$HOME/.chatarch" --json
```

Returns `directory` and `database`. Explicit `--home` takes precedence over ChatEnv's default home. User directories and defined environment variables expand; unknown variables and unsafe instance names are rejected. This command creates no directories, databases or accounts.

## Product Demo

```bash
python -m pip install "ChatLogin[demo]"
chatlogin serve
chatlogin serve --host 127.0.0.1 --port 8765 \
  --origin https://login.example.com
chatlogin serve --managed-demo
```

The default bind is `127.0.0.1:8765`. A non-loopback bind fails unless `--origin` is explicit. Behind a proxy, set it to the fixed browser-visible origin; the command never infers it from forwarded headers. The site uses only a public synthetic identity, short bounded sessions, and a disposable in-memory fixture. See the [Demo Guide](demo.md).

```text
Usage: chatlogin serve [OPTIONS]

Options:
  --host TEXT           Bind address; loopback by default.  [default: 127.0.0.1]
  --port INTEGER RANGE  TCP port.  [default: 8765; 1<=x<=65535]
  --origin TEXT         Fixed trusted public origin for browser Host/Origin checks.
  --managed-demo        Serve the disposable managed-users demonstration.
  --help                Show this message and exit.
```

`--managed-demo` explicitly selects the three-account in-memory demo; default `serve` continues to run the legacy four-backend demo. It requires the managed Core/Web preset and never reads a production/home user store.

## First Managed-User Bootstrap

```bash
# APP_BOOTSTRAP_CREDENTIAL is a variable name in a controlled environment, not a password value on the command line.
chatlogin users bootstrap operator \
  --instance my-site \
  --password-env APP_BOOTSTRAP_CREDENTIAL \
  --display-name "Operator" \
  --json
```

This command has one purpose: create the first owner in an explicitly empty instance. Ordinary arguments use ChatStyle `-i/--interactive` prompts or `-I/--no-interactive` fast failure; neither path accepts a raw password or automatically confirms creation. It validates path, instance, and environment-variable presence before a write where possible; repeat initialization and unsafe state fail nonzero, with no `--force` or chmod repair. Success emits only the safe user record. Use the Web/API for later account management; see [Managed Users](managed-users.md).

## Verification

```bash
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
```

The full tree above is an actual `chatlogin --tree` readback and the compact tree comes from `chatlogin --tree-brief`. Update tests and this page when adding commands. See [Integration and Security](integration.md) for website integration.
