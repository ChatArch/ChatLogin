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

The core package does not require adopting the packaged page. An existing static HTML/vanilla-JS site can mount only JSON routes and retain its current entry page and user database.

## Boundaries

- `guest`, `user`, and `admin` are server-trusted identities and cannot be selected from a request body.
- Fixed credentials, multiple accounts, and host callbacks are supported; existing PBKDF2 material can be verified without forced migration.
- Session tokens are persisted only as SHA-256 digests, with TTL, rotation, revocation, CSRF, and instance isolation.
- The FastAPI adapter enforces same-site Origin/Host checks, body-size limits, rate limiting, and safe local `next` values.
- Packaged templates provide independent palettes, layouts and light/dark/system appearance. Hosts can override part or all of the page, or keep their existing HTML/JS and use headless integration.
- Admin does not bypass resource ownership; host applications retain business-data authorization.
- There is no default production password, standalone login microservice, SSO/OAuth, MFA, or admin console.

## Development and Verification

```bash
python -m pip install -e ".[dev,docs]"
chatlogin --version
chatlogin --tree
python -m pytest -q
python -m build
python -m twine check dist/*
mkdocs build --strict
```

A runnable FastAPI demo with a synthetic account is available in `examples/demo_fastapi.py`.
