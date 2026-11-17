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

## Frontend Package

- Keep the framework-neutral client under `packages/chatlogin/src/client.ts`; React stays in the optional `@chatarch/chatlogin/react` subpath. Never add frontend credential/session persistence or Node authentication policy.
- Build with `cd packages/chatlogin && npm ci --ignore-scripts && npm run build`. Commit generated Python `web/assets/client.js` and `ui.js`; Python installation must not require Node.
- Python `web/assets/login.css` and `account-menu.css` are the CSS source. Build copies them to npm `styles/`; do not edit the copies directly.
- Verify `python packages/chatlogin/scripts/http_contract.py --check` in a Python environment with `ChatLogin[web]` plus the test transport `httpx>=0.27,<1.0`, then package-local `npm run check:shared`, `npm test`, `npm run typecheck`, and `npm run pack:check`. HTTPX is a test dependency, not a production web requirement.
- When changing the HTTP contract, regenerate fixtures with `python packages/chatlogin/scripts/http_contract.py`, review the diff, and update docs and both frontends together. Same-origin Cookie/CSRF and server-side authorization remain authoritative.
- Registry publishing is a distinct reviewed release. Do not equate a source commit, local tarball, or green package CI with an npm release.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.
