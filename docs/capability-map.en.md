# Capability Map

## Implemented Capabilities

| Capability | Status | Boundary |
| --- | --- | --- |
| Packaged demo | Implemented (`demo` extra) | `chatlogin serve`, four backend experiences, a template playground, and copyable integration examples; no production data |
| Identity and authorization | Implemented | `Principal`, `Role`, 401/403, `require_role`, and `require_owner`; admin does not bypass ownership |
| Credential backends | Implemented | `PasswordBackend` supports one or more explicit accounts; `CallbackBackend` integrates host user stores; `AsyncCallbackBackend` awaits async upstream verification |
| ChatVoice compatibility backend | Implemented (core, opt-in import) | `ChatVoiceAuth` / `ChatVoiceSessionStore`; existing ChatVoice schema, fixed namespace and USER only; no schema migration or ChatVoice/web dependency |
| Legacy password verification | Implemented | `verify_pbkdf2` verifies existing PBKDF2-HMAC-SHA256 salt/digest material without forced password migration |
| Sessions | Implemented | Opaque token, SHA-256-only storage, TTL, rotation, revocation, separate CSRF secret, and public `purge_expired()`; memory storage is demo/test-only |
| SQLite storage | Implemented | Public `PrivateSQLite` plus an instance-namespaced session store; POSIX uses a trusted `0700` directory and real-path `mode=rw`, rejects unsafe existing databases/sidecars, and does not present fd aliases as sidecar protection |
| FastAPI adapter | Implemented (`web` extra) | Configurable prefix, cookie, Origin/Host, body bound, rate limiting, JSON/headless routes, and dependencies |
| Default login UI | Implemented (`ui` or `web` extra) | `ui` installs only Jinja2; `web` also installs FastAPI/Starlette; wheel-packaged templates/CSS/JS |
| Web dependency compatibility gate | Implemented | `web`/`dev` declare `starlette>=0.40,<2.0`; compatibility tests cover Starlette 0.x, 1.3.1 and 1.6.0, and CI pins 0.x plus 1.3.x gates |
| Host template override | Implemented | Preferred template directories, block inheritance, whole-page renderer, and local custom stylesheet |
| ChatEnv namespace | Implemented | Keeps the `ChatLogin` typed profile without inventing an API key field |

## Integration Choices

1. **New site:** start with default UI plus `PasswordBackend` or a host callback.
2. **Custom visual identity:** keep the FastAPI adapter and replace template directories, template name, or renderer through `LoginUI`.
3. **Existing ChatVoice schema:** select `ChatVoiceAuth`; keep host HTTP/frontend or pass its `backend` / `manager` to the generic FastAPI adapter. Default UI, overrides and headless are all supported.

Backend selection: fixed/multiple accounts use `PasswordBackend`; sync host databases use `CallbackBackend`; async host databases use `AsyncCallbackBackend`; the ChatVoice schema uses ready-made `ChatVoiceAuth`. See the [selection matrix](integration.en.md).

## Out of Scope

- No standalone production login microservice, SSO, OAuth/email login, MFA, or admin console.
- ChatLogin does not own meetings, files, cards, or other business data; hosts retain owner and policy decisions.
- Guest is not a database account; guest experiences must be explicitly declared by the host.
- No universal ORM or backend registry; the ChatVoice backend promotes our existing bridge with synthetic legacy-schema regression coverage.
- Secrets, cookies, CSRF tokens, Authorization headers, and production credentials are never logged.

## Multi-User Boundary

Account mappings, callbacks, and the ChatVoice-compatible backend support multiple identities. `require_owner` is a host-invoked ownership check, not automatic database row-level security. Different users require distinct stable user IDs. See the [A/B lab and responsibility split](demo.en.md#user-isolation).
