# Python Interface Tree

## Current Interfaces

```text
chatlogin
├── __version__             # Installed package version
├── cli.main                # Click command-line entry point
└── config.ChatLoginConfig  # ChatEnv extension point without domain fields
```

```python
from chatlogin import __version__
from chatlogin.config import ChatLoginConfig
```

`ChatLoginConfig` uses the single `ChatLogin` namespace. It requires no API key, writes no user data and makes no network requests.

## Scope

This initial template has no authentication service, session store, user database or login page. Future domain behavior should be exposed through importable Python APIs with a thin CLI adapter.
