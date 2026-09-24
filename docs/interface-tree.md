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
├── PrivateSQLite(database, timeout=5)
│   └── connect(immediate=False)
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
├── ChatVoiceAuth(connect, lock, clock, *, ttl, max_sessions=10000)
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
      script_url=None,
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
from chatlogin import PrivateSQLite, SQLiteSessionStore, state_paths

paths = state_paths("my-site")
store = SQLiteSessionStore.for_instance("my-site")
private = PrivateSQLite(paths.directory / "leaf-package.sqlite3")
```

默认 session 路径为 `<ChatArch home>/chatlogin/instances/<instance>/sessions.sqlite3`。导入包和仅计算路径不会创建对象；初始化 `PrivateSQLite` 或 store 时才安全创建缺失的私有目录与主库。叶子包可以用 `with private.connect() as connection:` 复用相同边界，并在上下文正常退出时提交、异常时回滚；`immediate=True` 会在交付连接前执行 `BEGIN IMMEDIATE`。

POSIX 实现逐级 no-follow 校验祖先 owner 与写权限，要求最终数据目录由服务 UID 拥有且恰为 `0700`。主库以真实 file URI 的 `mode=rw` 打开；已有主库和 sidecar 必须是服务 UID 拥有、单链接、恰为 `0600` 的普通文件，绝不 chmod 历史对象。SQLite 在可信父目录中新建的安全 sidecar 才可按需规范为 `0600`。这套边界不依赖 fd alias，也不排除同 UID 进程；同 UID 与 root 在信任边界内。

缺少所需 dir-fd/no-follow 原语的 POSIX 平台失败关闭。非 POSIX 保留隔离的旧路径行为，不把 mode bits 当作 Windows ACL 保证；宿主仍需用平台 ACL 保护目录。此 API 面向可信本地文件系统，不支持网络/共享文件系统。

宿主需要清理私有上下文索引时，调用 `SessionManager.purge_expired()`，由 manager 使用已验证 instance 与 clock 委托给 store；不要复制 TTL 计算或访问 store 私有成员。
## 包内演示应用

安装 `ChatLogin[demo]` 后，`chatlogin.demo.create_demo_app(origin=...)` 返回完整的隔离演示应用；`chatlogin serve` 是对应的薄 CLI。它展示真实后端和 UI，但不充当生产身份中心。见 [快速接入](quickstart.md) 与 [演示站](demo.md)。

## 演示宿主的隔离接口

这些接口只在开发预览的演示应用中挂载，不属于生产账号管理API。

| 请求 | 契约 |
| --- | --- |
| `GET /api/demo/accounts` | 仅返回写死的公开合成A/B凭据，不查宿主用户库 |
| `GET /api/demo/{mode}/records` | 登录后仅列出本人样例 |
| `GET /api/demo/{mode}/records/{id}` | 当前用户必须为owner |
| `POST /api/demo/{mode}/records/{id}/touch` | 同源、当前会话CSRF、owner；不接受请求body |

参见[多用户边界](demo.md#user-isolation)。
