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
├── AsyncCredentialBackend            # Protocol: async authenticate(username, password)
├── PasswordBackend(accounts)         # 固定单账号或多账号
├── CallbackBackend(authenticate)     # 宿主用户库/已有哈希验证
└── AsyncCallbackBackend(authenticate) # 异步宿主用户库/上游验证

chatlogin
├── SessionStore                      # Protocol
├── MemorySessionStore(max_sessions)  # demo/test only
├── SQLiteSessionStore(database)
├── SQLiteSessionStore.for_instance(instance, home=None)
├── Session / IssuedSession
└── SessionManager(store, instance, ttl)
    ├── issue(principal, previous_token=None)
    ├── resolve(token)
    ├── purge_expired()
    ├── revoke(token)
    └── digest(token)

chatlogin
├── require_csrf(session, submitted)
├── safe_next(value, default="/")
└── LoginRateLimiter(limit, window, max_keys)
```

## 内建可选 ChatVoice 后端

```text
chatlogin.backends.chatvoice
├── ChatVoiceAuth(connect, lock, clock, *, ttl)
│   ├── login(account, password) -> IssuedSession | None
│   ├── resolve_row(token) -> dict | None
│   ├── check_csrf(auth, submitted)
│   ├── logout(token)
│   └── store / backend / manager
└── ChatVoiceSessionStore(connect, lock, clock, *, max_sessions=10000)
    ├── put(instance, digest, session, *, previous_digest=None)
    ├── get(instance, digest) / read_row(instance, digest)
    ├── session_from_row(row)
    ├── delete(instance, digest)
    └── purge_expired(instance, now)
```

核心包即可导入，两类也从 `chatlogin.backends` 导出。固定 ChatVoice schema / `chatvoice` 命名空间，只产生 USER 身份；不建表、不迁移、不负责账号创建、HTTP 或 owner 权限。接入与三种 UI 模式见 [接入文档](integration.md)。

## FastAPI 适配层

安装 `ChatLogin[web]` 后可用。`FastAPIAuth` 可接收同步 `CredentialBackend` 或异步 `AsyncCredentialBackend`；同步调用会在线程池执行，异步调用会被 await。

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

仅渲染 UI 时安装 `ChatLogin[ui]` 即可；它只引入 Jinja2，不要求 FastAPI。`ChatLogin[web]` 包含 UI 与 FastAPI/Starlette 适配层。

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

异步上游使用 `AsyncCallbackBackend`：

```python
from chatlogin import AsyncCallbackBackend, Principal

async def authenticate(username: str, password: str) -> Principal | None:
    row = await upstream.verify(username, password)
    return Principal(row.id, row.display_name) if row else None

backend = AsyncCallbackBackend(authenticate)
```

同步和异步 callback 都会先验证 username/password 的 UTF-8 字节上限。非法输入不会调用宿主回调；宿主必须返回已认证 `Principal` 或 `None`，guest/其他对象会失败关闭。

宿主仍拥有账户表、密码材料、业务资源 owner 和权限策略。ChatLogin 不创建默认生产账号，也不把 `admin` 角色解释成可访问所有业务数据。

## 运行态路径

```python
from chatlogin import SQLiteSessionStore, state_paths

paths = state_paths("my-site")
store = SQLiteSessionStore.for_instance("my-site")
```

默认路径为 `<ChatArch home>/chatlogin/instances/<instance>/sessions.sqlite3`。导入包和仅计算路径都不会创建目录；store 初始化时只创建自己的私有目录与 `0600` 数据库，不修改共享父目录权限。

宿主需要清理私有上下文索引时，调用 `SessionManager.purge_expired()`，由 manager 使用已验证 instance 与 clock 委托给 store；不要复制 TTL 计算或访问 store 私有成员。
