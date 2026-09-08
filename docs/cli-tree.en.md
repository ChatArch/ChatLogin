# CLI Tree

Authentication and web behavior are [Python APIs](interface-tree.md). The CLI provides version information and side-effect-free runtime-path inspection, not another login service.

## Top-Level Commands

```text
chatlogin
├── --help                                      # Show help
├── --version                                   # Query installed version
├── --tree                                      # Actual tree with arguments
├── --tree-brief                                # Compact tree
└── paths <INSTANCE> [--home HOME] [--json]      # Inspect instance runtime paths
```

## Path Inspection

```bash
chatlogin paths my-site --json
chatlogin paths my-site --home "$HOME/.chatarch" --json
```

Returns `directory` and `database`. Explicit `--home` takes precedence over ChatEnv's default home. User directories and defined environment variables expand; unknown variables and unsafe instance names are rejected. This command creates no directories, databases or accounts.

## Verification

```bash
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
```

The tree comes directly from registered ChatStyle/Click metadata. Update tests and this page when adding commands. See [Integration and Security](integration.md) for website integration.
