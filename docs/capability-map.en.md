# Capability Map

## Implemented Capabilities

| Capability | Status | Boundary |
| --- | --- | --- |
| Identity and authorization | Implemented | `Principal`, `Role`, 401/403, `require_role`, and `require_owner`; admin does not bypass ownership |
| Credential backends | Implemented | `PasswordBackend` supports one or more explicit accounts; `CallbackBackend` integrates host user stores |
| Legacy password verification | Implemented | `verify_pbkdf2` verifies existing PBKDF2-HMAC-SHA256 salt/digest material without forced password migration |
| Sessions | Implemented | Opaque token, SHA-256-only storage, TTL, rotation, revocation, and a separate CSRF secret; memory storage is demo/test-only |
| SQLite storage | Implemented | Namespaced by instance, `0600` database, private newly created directories, no chmod on shared parents |
| FastAPI adapter | Implemented (`web` extra) | Configurable prefix, cookie, Origin/Host, body bound, rate limiting, JSON/headless routes, and dependencies |
| Default login UI | Implemented (`web` extra) | `indigo/forest/amber` palettes and `card/split` layouts; wheel-packaged templates/CSS/JS |
| Host template override | Implemented | Preferred template directories, block inheritance, whole-page renderer, and local custom stylesheet |
| ChatEnv namespace | Implemented | Keeps the `ChatLogin` typed profile without inventing an API key field |

## Integration Choices

1. **New site:** start with default UI plus `PasswordBackend` or a host callback.
2. **Custom visual identity:** keep the FastAPI adapter and replace template directories, template name, or renderer through `LoginUI`.
3. **Existing native frontend, such as ChatVoice:** omit `LoginUI`, keep the original HTML/CSS/JS and user database, and reuse the headless JSON API with a callback backend.

## Out of Scope

- No standalone login microservice, SSO, OAuth/email login, MFA, or admin console.
- ChatLogin does not own meetings, files, cards, or other business data; hosts retain owner and policy decisions.
- Guest is not a database account; guest experiences must be explicitly declared by the host.
- Unknown upstream code is not copied; the ChatVoice integration extracts a behavior contract.
- Secrets, cookies, CSRF tokens, Authorization headers, and production credentials are never logged.
