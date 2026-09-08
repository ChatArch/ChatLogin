# Python 接口树

## 核心层

```text
chatlogin
├── __version__
├── Principal / Role
│   ├── Principal.guest()
│   └── principal.authenticated
├── require_user(principal)
├── require_role(principal, *roles)
└── require_owner(principal, owner_id)

chatlogin
├── PasswordHash
├── hash_password(password)
├── verify_pbkdf2(password, salt, digest, iterations=310000)
├── CredentialBackend                 # Protocol: authenticate(username, password)
├── PasswordBackend(accounts)         # 固定单账号或多账号
└── CallbackBackend(authenticate)     # 宿主用户库/已有哈希验证

chatlogin
├── SessionStore                      # Protocol
├── MemorySessionStore(max_sessions)  # demo/test only
├── SQLiteSessionStore(database)
├── SQLiteSessionStore.for_instance(instance, home=None)
├── Session / IssuedSession
└── SessionManager(store, instance, ttl)
    ├── issue(principal, previous_token=None)
    ├── resolve(token)
    ├── revoke(token)
    └── digest(token)

chatlogin
├── require_csrf(session, submitted)
├── safe_next(value, default="/")
└── LoginRateLimiter(limit, window, max_keys)
```

## FastAPI 适配层

安装 `ChatLogin[web]` 后可用：

```text
chatlogin.fastapi
├── FastAPIAuth
│   ├── router
│   ├── current_user(request) -> Principal
│   ├── csrf_user(request) -> Principal
│   ├── roles(*roles) -> FastAPI dependency
│   └── cookie / sessions / ui
├── CookieSettings(name, path, max_age, secure, same_site, http_only)
├── GET  {prefix}/session
├── POST {prefix}/login
└── POST {prefix}/logout
```

传入 `LoginUI` 时额外注册：

```text
GET {prefix}/                  # 默认或宿主覆盖的登录页
GET {prefix}/assets/login.css
GET {prefix}/assets/login.js
```

不传 `LoginUI` 时没有页面和静态资源，适合宿主保留原前端的 headless 接入。

## UI 层

```text
chatlogin.ui
└── LoginUI(
      title,
      subtitle,
      palette="indigo" | "forest" | "amber",
      layout="card" | "split",
      appearance="system" | "light" | "dark",
      guest_url=None,
      guest_label="以访客身份继续",
      template_dirs=(),
      template_name="chatlogin/login.html",
      stylesheet_url=None,
      renderer=None,
    )
```

宿主模板放在 `template_dirs` 中并优先于包内模板。可以 `{% extends "chatlogin/login.html" %}` 覆盖单个 block，也可以提供整页模板，或传入直接返回 HTML 的 renderer。

## 最小后端接入

```python
from chatlogin import CallbackBackend, Principal, Role, verify_pbkdf2

def authenticate(username: str, password: str) -> Principal | None:
    row = my_user_database.find(username)
    if row and verify_pbkdf2(password, row.salt, row.digest, iterations=row.iterations):
        return Principal(row.id, row.display_name, Role(row.role))
    return None

backend = CallbackBackend(authenticate)
```

宿主仍拥有账户表、密码材料、业务资源 owner 和权限策略。ChatLogin 不创建默认生产账号，也不把 `admin` 角色解释成可访问所有业务数据。

## 运行态路径

```python
from chatlogin import SQLiteSessionStore, state_paths

paths = state_paths("my-site")
store = SQLiteSessionStore.for_instance("my-site")
```

默认路径为 `<ChatArch home>/chatlogin/instances/<instance>/sessions.sqlite3`。导入包和仅计算路径都不会创建目录；store 初始化时只创建自己的私有目录与 `0600` 数据库，不修改共享父目录权限。
