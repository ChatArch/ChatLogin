# Development Guide

## CLI Rules

- Use `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.11,<0.3.0` as the canonical CLI interaction runtime.
- Use `add_tree_option()` for shared `--tree` / `--tree-brief` flags and `render_click_tree()` for programmatic Click-tree readback.
- Prefer `CommandSchema`, `CommandField`, `add_interactive_option()`, and `resolve_command_inputs()` for new commands.
- Missing required args should auto-enter interactive mode when recoverable.
- `-i` forces interactive mode; `-I` disables prompting and must fail fast.
- Prompt defaults must match actual execution defaults.
- Sensitive values must stay masked in prompts and summaries.
- Prefer lazy imports in CLI wiring and keep implementation imports local when possible.
- Managed-user bootstrap accepts an environment-variable name, never a raw password argument; keep it explicit, non-forcing, and backed by `ManagedUsers` rather than CLI policy.

## Docs and Tests

- Use doc-first CLI testing.
- Put real CLI coverage under `tests/cli-tests/`.
- Put mock/fake CLI coverage under `tests/mock-cli-tests/`.
- Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.
- Keep managed-user CLI trees and bilingual `managed-users` guidance synchronized with actual registered commands and provider APIs.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.
