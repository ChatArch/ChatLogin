# 演示站与快速开始

在线体验：[ChatLogin 演示站](https://login.public.wzhecnu.cn/) · [模板游乐场](https://login.public.wzhecnu.cn/templates)。这是公开合成账号环境，不连接真实业务数据。

`chatlogin serve` 从**已安装的 ChatLogin wheel** 读取并运行产品演示，不依赖源码相对路径。它用于选择认证后端、前端接入方式和 `LoginUI` 配置，不是共享生产身份服务。

## 安装与启动

```bash
python -m pip install "ChatLogin[demo]"
chatlogin serve
```

默认地址为 <http://127.0.0.1:8765/>。`demo` extra 自包含 FastAPI、Starlette、Jinja2 与 Uvicorn；核心包仍不强制安装这些 Web 依赖。

```text
Usage: chatlogin serve [OPTIONS]

Options:
  --host TEXT           Bind address; loopback by default.  [default: 127.0.0.1]
  --port INTEGER RANGE  TCP port.  [default: 8765; 1<=x<=65535]
  --origin TEXT         Fixed trusted public origin for browser Host/Origin checks.
  --help                Show this message and exit.
```

如果由反向代理提供 TLS，仍把进程绑定到 loopback，并显式传入浏览器实际访问的可信 origin：

```bash
chatlogin serve \
  --host 127.0.0.1 \
  --port 8765 \
  --origin https://login.example.com
```

`--origin` 是固定安全配置，不从 `Host`、`X-Forwarded-Host` 或 `X-Forwarded-Proto` 自动推导。代理、TLS、进程监督和公网限流仍由部署方负责。

## 可以实际体验什么

开发预览提供公开合成A/B账号，登录页可选择并填入。它们不对应真实账户或客户数据，详见[多账号与数据隔离](#user-isolation)。

| 后端 | 前端 | 入口 | 数据来源 |
| --- | --- | --- | --- |
| `PasswordBackend` | 默认 `LoginUI` | `/demo/password/` | 显式构造的两个独立账号与密码hash |
| `CallbackBackend` | 宿主 `renderer` 覆盖 | `/demo/callback/` | 本地同步合成回调 |
| `AsyncCallbackBackend` | `ui=None` + 自有 HTML/JS | `/experience/async` | 本地异步合成回调 |
| `ChatVoiceAuth` | `LoginUI` split/dark | `/demo/chatvoice/` | 一次性共享内存 SQLite 旧 schema fixture |

四种模式各自使用 cookie 名与 session namespace。登录成功后的工作区显示安全身份、宿主拥有的合成记录、真实数据归属校验，以及受保护读取、CSRF检查与退出操作。页面与日志不展示 session token、cookie、密码 hash 或 CSRF 值。CSRF 只在同源 session/login JSON 中返回给浏览器以执行安全写操作；会话 token 只通过 HttpOnly Cookie 交付。

模板游乐场在 `/templates`，预览由实际 `LoginUI.render()` 生成。它只接受三个色板、两个布局、`light`/`dark`/`system` 与 guest 开关，并生成可复制的精确 Python 配置；不接受任意 HTML 或文件路径。

健康与版本读回：

```text
GET /health   -> {"status":"ok","version":"0.1.6.dev2"}
GET /version  -> {"version":"0.1.6.dev2"}
```

## 多账号与数据隔离 {#user-isolation}

A/B隔离实验在 `0.1.6.dev2` 开发预览可用；`0.1.5` 的认证核心已经支持多账号，但它的演示只公示一个账号。以站点页眉或 `chatlogin --version` 为准，开发预览不等于新的PyPI正式版本。

| 层次 | 负责方 | 验证方式 |
| --- | --- | --- |
| 多账号认证 | `PasswordBackend` 映射、同步/异步回调、`ChatVoiceAuth` 账户库 | A/B返回不同且稳定的 `user_id` |
| 用户会话 | ChatLogin会话存储与HttpOnly Cookie | 两个独立浏览器会话互不串号；退出A不影响B |
| 业务数据 | 宿主按可信身份过滤、调用 `require_owner` | 本人列表/详情/写入成功；持A会话读写B样例返回403，反向相同 |

每个后端演示都有两组**公开合成凭据**：A为 `demo` / `chatlogin-demo`，B为 `demo-b` / `chatlogin-demo-b`。登录页选择账号并填入，再点击登录。不要用两个普通标签假装独立用户：它们共享Cookie；并行验证使用普通与无痕窗口，或两个浏览器。

登录后的“用户数据隔离”提供本人读取、本人修改、读取对方、修改对方四个真实API操作。修订号由服务端修改；数据未预先全部下发再由前端隐藏。归属来自服务端 `Principal.user_id`，不接受客户端指定 `owner_id`。公开的对方资源ID仅用于合成越权测试，不应成为真实产品的目录枚举接口。

这是应用层逻辑隔离，不是每人独立数据库。ChatVoice宿主也可按 `(owner_id, record_id)` 查询并对不存在于当前用户空间的详情返回404。登录库不自动隔离会议、文件、下载、后台任务或其他业务表：宿主必须在每个入口执行自己的授权规则。每个真实用户必须拥有稳定且不同的 `user_id`，不能让多个账号都返回同一Principal。

样例业务记录仅驻留当前演示进程，重启清空；它们没有任何真实业务权限。演示账号公开，所以任何访问者都可主动登录A或B；隔离结论是**持A会话不能越权访问B资源**，不是对知道B凭据的访问者保密。

## 演示安全边界

- 每个后端最多 16 个有效 session，TTL 为 5 分钟；满载时返回可重试的 HTTP 503，不驱逐其他有效 session。
- Memory 模式仅存在于当前进程；ChatVoice fixture 只存在于当前共享内存 SQLite 生命周期，不写用户 home。
- 认证与私有响应使用 `no-store`，cookie 为 `HttpOnly`、固定 path、`SameSite=Strict`，HTTPS origin 时启用 `Secure`。
- 所有浏览器 POST 使用固定同源检查；已有 cookie 的重复登录先读取 session，并携带当前 CSRF 后再轮换。
- 静态资源经 `importlib.resources` 从包内 allowlist 读取，带正确 content type；页面 CSP 不依赖外部 CDN。
- 演示不读取 ChatEnv profile、生产 provider、真实账号数据库或任意 forwarded header。

## 用于真实项目

生产项目应安装 `ChatLogin[web]`，选择自己的 `CredentialBackend`、`SessionStore`、固定 origin 和业务授权策略。默认 UI、宿主模板覆盖与 headless 是彼此独立的前端选择，不是 OAuth/短信等认证协议。

- [接入与安全](integration.md)：完整 FastAPI、覆盖模板、headless sequence、回调、ChatVoice schema 与 store 选择。
- [能力地图](capability-map.md)：当前实现与明确排除项。
- [Python 接口树](interface-tree.md)：实际构造签名与 HTTP 路由。

ChatLogin 不提供默认生产密码、OAuth、SSO、MFA、邮件/短信验证码、扫码登录、账号后台或跨业务身份中心。
