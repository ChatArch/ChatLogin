# 接入与安全边界

## 选择接入层级

| 需求 | 入口 | 网站保留的责任 |
| --- | --- | --- |
| 新站直接获得登录页 | `FastAPIAuth(..., ui=LoginUI(...))` | 用户来源、业务路由、部署与 TLS |
| 自有品牌和样式 | `LoginUI(template_dirs=..., template_name=...)` 或 `renderer` | 自定义 HTML/CSS、renderer 内容安全 |
| 已有 HTML/JS 前端 | `FastAPIAuth(..., ui=None)` | 原页面、前端状态与所有业务数据 |
| 保持已有 HTTP/数据库契约 | `CallbackBackend` + `SessionManager` + 宿主 `SessionStore` | 原账号 ID、密码材料、数据库/会话映射、响应兼容 |
| 标准库 HTTP 页面 | `LoginUI(...).render(context)` + `ChatLogin[ui]` | HTTP handler、cookie、Origin/CSRF、响应字段 |

Headless 不等于另起认证微服务。可以在同一个 FastAPI 进程挂载 JSON 路由，也可以只调用核心 Python API，保留既有 HTTP handler 与 JSON 字段。普通 Python 包即可携带 HTML/CSS/JS；安装位置不是定制入口，宿主模板目录优先于包内模板。

## 选择认证后端

| 账户来源 | 入口 | 责任 |
| --- | --- | --- |
| 固定账号 / 多账号 | `PasswordBackend(accounts)` | 配置一个 / 多个显式 `Principal` 与 `PasswordHash`，搭配所选 `SessionStore` |
| 其他宿主用户库 | `CallbackBackend(authenticate)` + 宿主 `SessionStore` | 宿主定义验证和映射；不要套用 ChatVoice schema |
| 异步上游服务 | `AsyncCallbackBackend(authenticate)` + `SessionManager` | await 宿主回调；非法输入不调用上游，非法返回值失败关闭 |
| 既有 ChatVoice 账户与会话 | `ChatVoiceAuth` | 内建、可选的现成兼容后端，不依赖 ChatVoice 包或 `web` extra |

`CallbackBackend` 与 `AsyncCallbackBackend` 使用同一输入边界：用户名 1..256 UTF-8 字节，密码 1..1024 UTF-8 字节。返回值必须是已认证 `Principal` 或 `None`；不要把上游私有 Authorization、模型 key、Dufs/Overleaf 凭据或 relay 上下文写入 `Principal` metadata、session JSON 或 UI payload。

### ChatVoice schema 兼容后端

```python
from chatlogin.backends import ChatVoiceAuth

# host 是宿主对象；回调每次解析当前连接、锁与时钟，不捕获数据库路径。
auth = ChatVoiceAuth(
    lambda: host.open_auth_connection(),
    lambda: host.auth_lock,
    lambda: host.utc_now().timestamp(),
    ttl=86400,
)
# 已有 HTTP handler 可直接使用：
# auth.login(account, password) -> IssuedSession | None
# auth.resolve_row(token) -> dict | None
# auth.check_csrf(auth_row, submitted) -> None，失败抛 AccessDenied
# auth.logout(token) -> None
```

连接工厂必须返回新的 `sqlite3.Connection`（`row_factory=sqlite3.Row`，启用 `PRAGMA foreign_keys=ON`，无未提交事务）；每次操作会关闭连接。宿主负责初始化既有 schema、文件权限与账号创建：

- `accounts(id TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, password_salt BLOB NOT NULL, password_hash BLOB NOT NULL, created_at TEXT NOT NULL)`。
- `auth_sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf_token TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)`，`user_id` 外键指向 `accounts(id) ON DELETE CASCADE`。

这是 **ChatVoice schema 专用兼容**，不是任意 SQLite 账户系统的通用 ORM。账户名精确匹配，宿主若已有大小写/空白规范化须在调用前保留。密码保持 PBKDF2-HMAC-SHA256、310000 次与原有 salt/digest；保留原账号 ID、ISO expiry（含时区偏移）、32 字符旧 CSRF 与 SHA-256 token 摘要。匿名、失效或错误凭据不会创建身份。每次解析重新 join 账号，不缓存用户快照。

`ChatVoiceSessionStore(connect, lock, clock, *, max_sessions=10000)` 只接受 `chatvoice` 命名空间与 `Role.USER` 会话，拒绝 guest/admin。容量按整个数据库计算，跨 store 实例由 SQLite 事务串行化；不驱逐有效会话，满时抛 `StoreFull`。`SessionManager.issue(..., previous_token=...)` 原子替换，插入失败会回滚并保留旧会话。`ChatVoiceAuth` 保留原构造签名，store 默认上限为 10000；需要自定义上限时可单独组合该 store 与 manager。

### 与三种 UI 模式组合

安装 `ChatLogin[web]` 后，直接把同步或异步 backend 与 manager 交给通用适配层：

```python
from chatlogin.fastapi import FastAPIAuth
from chatlogin.ui import LoginUI

web = FastAPIAuth(auth.backend, auth.manager, origin="https://example.test",
                 ui=LoginUI())  # 默认 UI
# ui=LoginUI(template_dirs=("templates",), template_name="host/login.html")  # 宿主覆盖
# ui=None  # headless JSON；也可仅用上面的 Python 方法保留原 HTTP handler
app.include_router(web.router)
```

通用 HTTP adapter 保留原 JSON 字段与 Origin/Host、cookie、CSRF、限流策略，不自动变成 ChatVoice HTTP 接口。保留旧 HTTP 时，宿主继续负责 cookie 与响应映射、Origin/CSRF 检查、账户创建和所有业务 owner/policy；`resolve_row` 的 `_chatlogin_session` 供服务端 CSRF 校验，不能整行序列化或记录敏感字段。

如果不使用 FastAPI，只安装 `ChatLogin[ui]` 并调用 `LoginUI.render()`；此模式只负责模板渲染，安全 HTTP 行为仍由宿主实现。

## 浏览器 HTTP 契约

默认前缀是 `/auth`，可显式改为 `/api/auth` 等固定本地前缀。

| 请求 | 作用 | 条件 |
| --- | --- | --- |
| `GET {prefix}/session` | 当前身份和 CSRF；访客返回 `authenticated=false` | 同一可信 Host，不缓存 |
| `POST {prefix}/login` | 校验凭据并签发 cookie | JSON、精确 Origin、大小与频率上限；已有有效 cookie 时还需 CSRF |
| `POST {prefix}/logout` | 撤销当前会话并清 cookie | 精确 Origin 与 CSRF |
| `current_user` | 受保护读操作 | 无有效会话时 401 |
| `csrf_user` | cookie 认证的写操作 | 有效身份、精确 Origin 与 CSRF |
| `roles(...)` | 明确角色要求 | 认证失败 401，角色不足 403 |

浏览器使用 `credentials: 'same-origin'`，从 session JSON 读取 CSRF 值，在写操作的 `X-CSRF-Token` 请求头中发送。不要把密码、session cookie 或 CSRF 存入 localStorage/sessionStorage，也不要将值写入日志。浏览器会为同源 POST 生成 Origin，不需要脚本伪造该头。

`allow_native=True` 是显式开启的程序客户端登录例外：仅没有 Origin、没有浏览器 fetch-site 语义的初始登录可使用 `X-ChatLogin-Client: native`。这不是认证凭据；cookie 写操作仍要求规范 Origin 与 CSRF。默认不允许该例外，不启用跨站 CORS。

## 身份、权限与存储

- `guest` 是未认证状态，不自动创建用户、持久会话或复制访客历史。
- `user`/`admin` 只能来自受信任认证后端。多账户可使用 `PasswordBackend` 的多个显式条目，或接入已有数据库的 `CallbackBackend`。
- `require_owner` 对 admin 也执行相同的 owner 检查；宿主若允许管理员访问他人数据，必须另行明确授权。
- 会话随机 token 只交付 HttpOnly cookie；`SessionStore` 接收摘要，不接收原 token。CSRF 是单独的敏感值，允许传给同源客户端但不得记录。
- 过期清理通过 `SessionManager.purge_expired()` 触发，manager 会使用自身已验证的 instance 和 clock 调用 store。宿主需要维护私有上下文索引时，应以此为边界清理，不复制 TTL 或访问 store 私有字段。
- 内存 store 有容量上限，仅用于单进程演示/测试。SQLite 是持久本地方案；多主机部署需提供共享的 `SessionStore`。登录频率限制是进程级后备保护，不是分布式抗滥用服务。
- `origin` 应是部署的固定可信源；不从任意 Host 或 forwarded 头自动推断。反代信任、TLS 与宿主服务进程由网站负责。

## 依赖兼容门禁

`ChatLogin[web]` 当前声明 `starlette>=0.40,<2.0`。兼容性测试覆盖：

- 当前 0.x 线：338 passed / 6 browser-opt-in skipped。
- ChatShare 目标线：installed wheel with `FastAPI==0.133.1` + `Starlette==1.3.1`，338 passed / 6 skipped。
- 新 1.x 探针：installed wheel with `FastAPI==0.141.1` + `Starlette==1.6.0`，338 passed / 6 skipped。
- `ChatLogin[ui]` clean wheel install without FastAPI/Starlette rendered `LoginUI` successfully。

仓库的 `Web Compatibility` workflow 继续显式安装 0.x 与 1.3.x 线路，用正常 resolver 验证 `web` extra。1.x 功能探针已证明代码行为兼容；发布前仍需运行标准依赖解析与最低 Python wheel gate。

## 可运行演示

从源码分发或仓库根目录执行。演示不含默认口令，使用临时合成账号，不连接生产数据：

```bash
python -m pip install -e ".[web,demo]"
read -s CHATLOGIN_DEMO_PASSWORD
export CHATLOGIN_DEMO_PASSWORD
python -m uvicorn examples.demo_fastapi:create_app --factory --host 127.0.0.1 --port 10081
```

口令至少 12 个字符，演示账号名为 `demo`。打开 `http://127.0.0.1:10081/api/auth/`，登录后返回宿主首页，可点击退出；`/private` 是受保护读接口。此地址是本机测试入口，不是已部署的公共网站。

## 定制责任

默认模板对文本自动转义，并使用包内静态资源。自定义 renderer 被视为受信任的宿主代码，必须自行保证 HTML 安全。自定义颜色/CSS与业务权限相互独立，不要为换肤关闭 cookie、CSRF 或 owner 检查。
