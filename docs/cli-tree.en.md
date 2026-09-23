# CLI Tree

Reusable authentication and web behavior are [Python APIs](interface-tree.md). The CLI can also run the isolated product demo; it is not a production login service.

## Top-Level Commands

```text
chatlogin
├── --help                                      # Show help
├── --version                                   # Query installed version
├── --tree                                      # Actual tree with arguments
├── --tree-brief                                # Compact tree
├── paths <INSTANCE> [--home HOME] [--json]      # Inspect instance runtime paths
└── serve [--host HOST] [--port PORT] [--origin ORIGIN]
                                                    # Run the isolated synthetic demo
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
```

The default bind is `127.0.0.1:8765`. A non-loopback bind fails unless `--origin` is explicit. Behind a proxy, set it to the fixed browser-visible origin; the command never infers it from forwarded headers. The site uses only a public synthetic identity, short bounded sessions, and a disposable in-memory fixture. See the [Demo Guide](demo.md).

```text
Usage: chatlogin serve [OPTIONS]

Options:
  --host TEXT           Bind address; loopback by default.  [default: 127.0.0.1]
  --port INTEGER RANGE  TCP port.  [default: 8765; 1<=x<=65535]
  --origin TEXT         Fixed trusted public origin for browser Host/Origin checks.
  --help                Show this message and exit.
```

## Verification

```bash
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
```

The tree comes directly from registered ChatStyle/Click metadata. Update tests and this page when adding commands. See [Integration and Security](integration.md) for website integration.
