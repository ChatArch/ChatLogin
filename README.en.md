<div align="center">
    <a href="https://pypi.python.org/pypi/ChatLogin">
        <img src="https://img.shields.io/pypi/v/ChatLogin.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatLogin/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatLogin/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
    <a href="https://arch.gh.wzhecnu.cn/ChatLogin/">
        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# ChatLogin

ChatLogin provides reusable login primitives for Python-backed websites. The backend owns identity, credential verification, sessions, CSRF, safe redirects, and role boundaries. The frontend can use the packaged templates, override templates/CSS, or keep the host's original HTML/JavaScript against a headless JSON API.

Documentation: <https://arch.gh.wzhecnu.cn/ChatLogin/en/>

| Scenario | Document |
| --- | --- |
| FastAPI quick start | [Interface Tree](docs/interface-tree.en.md) |
| Default UI, overrides, and headless mode | [Capability Map](docs/capability-map.en.md) |
| CLI version and command tree | `docs/cli-tree.en.md` |

## Install

```bash
pip install "ChatLogin[web]"
```

For packaged template rendering without FastAPI, install only:

```bash
pip install "ChatLogin[ui]"
```

To run the packaged product demo (`demo` includes the web stack and Uvicorn):

```bash
pip install "ChatLogin[demo]"
chatlogin serve
# Open http://127.0.0.1:8765/
```

Behind a reverse proxy, keep the bind on loopback and explicitly set the trusted browser origin:

```bash
chatlogin serve --host 127.0.0.1 --port 8765 --origin https://login.example.com
```

`serve` is an isolated product demonstration with a public synthetic identity, bounded five-minute in-memory sessions, and a disposable ChatVoice schema fixture. It reads no ChatEnv account or production database, provides no default production credential, and is not a shared login microservice. See [Demo and Quick Start](docs/demo.en.md).

The core package does not require adopting the packaged page. An existing static HTML/vanilla-JS site can mount only JSON routes and retain its current entry page and user database; a standard-library HTTP host can use `LoginUI` for rendering without installing FastAPI.

## Choose an Authentication Backend (0.1.5)

| Account source | Optional backend | Session and host boundary |
| --- | --- | --- |
| Fixed account / multiple explicit accounts | `PasswordBackend(accounts)` | One / multiple hash entries, with `SessionManager` and a chosen store |
| Other host user database | `CallbackBackend(authenticate)` + host `SessionStore` | Host defines password verification, schema and session mapping |
| Async upstream verification | `AsyncCallbackBackend(authenticate)` | Callback is awaited in the event loop; invalid input is not called and invalid results fail closed |
| Existing ChatVoice account/session schema | `chatlogin.backends.ChatVoiceAuth` | Ready-made compatibility backend; fixed `chatvoice` namespace, no table creation or migration |

`ChatVoiceAuth` ships in the core package for opt-in import; it requires neither ChatVoice nor the `web` extra. It is not a generic ORM for arbitrary SQLite account systems. Default UI, host overrides and headless mode remain independent of backend selection. Account creation, business owner permissions and host HTTP contracts remain host responsibilities. See [Integration and Security](docs/integration.en.md).

## Boundaries

- `guest`, `user`, and `admin` are server-trusted identities and cannot be selected from a request body.
- Fixed credentials, multiple accounts, and host callbacks are supported; existing PBKDF2 material can be verified without forced migration.
- Session tokens are persisted only as SHA-256 digests, with TTL, rotation, revocation, CSRF, instance isolation, and public `SessionManager.purge_expired()` cleanup.
- Public `PrivateSQLite` is reusable by dependent packages. On POSIX it protects the main database and SQLite sidecars with a trusted `0700` data directory and real-path `mode=rw` connections, rejecting unsafe existing paths without chmodding historical files. Same-UID processes are inside the local-filesystem trust boundary; non-POSIX mode bits are not presented as ACL checks.
- The FastAPI adapter enforces same-site Origin/Host checks, body-size limits, rate limiting, and safe local `next` values.
- `ChatLogin[web]` declares `starlette>=0.40,<2.0`; compatibility tests cover Starlette 0.x, 1.3.1, and 1.6.0, while CI keeps explicit 0.x and 1.3.x gates.
- Packaged templates provide independent palettes, layouts and light/dark/system appearance. Hosts can override part or all of the page, or keep their existing HTML/JS and use headless integration.
- Admin does not bypass resource ownership; host applications retain business-data authorization.
- There is no default production password, standalone login microservice, SSO/OAuth, MFA, or admin console.

## Development and Verification

```bash
python -m pip install -e ".[dev,docs]"
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
python -m pytest -q
python -m build
python -m twine check dist/*
mkdocs build --strict
```

A runnable FastAPI synthetic-account example is available in `examples/demo_fastapi.py`; use `chatlogin serve` for the packaged interactive demo.
