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

[英文版](README.en.md) | [简体中文](README.md)
</div>

# ChatLogin

ChatLogin 是面向 Python-backed 网站的可复用登录能力包：后端统一处理身份、认证、会话、CSRF、回跳和角色边界；前端可以使用默认模板、覆盖模板/CSS，或保留网站原有 HTML/JS 走 headless JSON API。

文档入口：<https://arch.gh.wzhecnu.cn/ChatLogin/>

| 场景 | 文档 |
| --- | --- |
| FastAPI 快速接入 | [完整可运行应用](docs/quickstart.md) |
| 默认 UI、模板覆盖与 headless | [能力地图](docs/capability-map.md) |
| CLI 版本和命令树 | [CLI 树](docs/cli-tree.md) |

## 安装

```bash
pip install "ChatLogin[web]"
```

只需要包内模板渲染、但不使用 FastAPI 时可安装：

```bash
pip install "ChatLogin[ui]"
```

要直接体验包内产品演示（`demo` extra 已自包含 `web` 依赖与 Uvicorn）：

```bash
pip install "ChatLogin[demo]"
chatlogin serve
# 打开 http://127.0.0.1:8765/
```

反向代理时仍建议只绑定 loopback，并明确写出浏览器实际访问的可信源：

```bash
chatlogin serve --host 127.0.0.1 --port 8765 --origin https://login.example.com
```

`serve` 只运行隔离产品演示：公开合成身份、5 分钟有界内存会话与一次性 ChatVoice schema fixture。它不读取 ChatEnv 账号或生产数据库，不提供默认生产凭据，也不是可供多业务共享的登录微服务。详见[演示站与快速开始](docs/demo.md)。

核心包不要求网站采用包内页面。已有静态 HTML/原生 JS 的网站可以只挂载 JSON 路由，继续保留原登录入口和用户数据库；标准库 HTTP 宿主也可以只使用 `LoginUI` 渲染登录页。

## 选择认证后端（0.1.5）

| 账户来源 | 可选后端 | 会话与宿主边界 |
| --- | --- | --- |
| 固定账号 / 多个显式账号 | `PasswordBackend(accounts)` | 一个 / 多个哈希条目；搭配 `SessionManager` 与所选 store |
| 其他宿主用户库 | `CallbackBackend(authenticate)` + 宿主 `SessionStore` | 宿主定义密码验证、schema 和会话映射 |
| 异步上游校验 | `AsyncCallbackBackend(authenticate)` | 回调在事件循环中 `await`；非法输入不调用回调，非法结果失败关闭 |
| 已有 ChatVoice 账户/会话 schema | `chatlogin.backends.ChatVoiceAuth` | 现成兼容后端；固定 `chatvoice` 命名空间，不建表或迁移 |

`ChatVoiceAuth` 随核心包提供，按需导入；不依赖 ChatVoice 包或 `web` extra，不是任意 SQLite 账户系统的通用 ORM。默认 UI、宿主覆盖和 headless 三种模式与后端选择相互独立。账户创建、业务 owner 权限与宿主 HTTP 契约仍由网站负责。见 [接入与安全](docs/integration.md)。

## 设计边界

- `guest` / `user` / `admin` 是服务端可信身份，角色不能由请求体指定。
- 固定账号、多账号和宿主回调均可；已有 PBKDF2 密码材料可验证，不强制迁移。
- 会话 token 只以 SHA-256 摘要持久化，支持 TTL、轮换、撤销、CSRF、实例隔离和公开 `SessionManager.purge_expired()` 清理。
- 公开 `PrivateSQLite` 供依赖包复用；POSIX 上以可信 `0700` 数据目录和真实路径 `mode=rw` 连接保护主库及 SQLite sidecar，拒绝不安全的已有路径且不 chmod 历史文件。同 UID 进程属于本地文件系统信任边界；非 POSIX 不把 mode bits 误称为 ACL。
- FastAPI adapter 默认同站 Origin/Host 校验、请求体大小限制、限流和安全 `next`。
- `ChatLogin[web]` 声明 `starlette>=0.40,<2.0`；兼容性测试覆盖 Starlette 0.x、1.3.1 和 1.6.0，CI 门禁继续固定 0.x 与 1.3.x 线路。
- 默认模板提供色系、布局与浅色/深色/跟随系统选项；宿主可覆盖局部或整页，也可保留原 HTML/JS 走 headless。
- Admin 不自动绕过资源 owner；业务数据授权仍由宿主决定。
- 不提供默认生产密码、独立登录微服务、SSO/OAuth、MFA 或账户管理后台。

## 开发与验证

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

可运行的 FastAPI 合成账号示例：`examples/demo_fastapi.py`；包内交互演示：`chatlogin serve`。

### 多用户与数据隔离

认证后端支持多个账号，每个用户需要不同且稳定的 `user_id`。会话归ChatLogin，业务资源授权归宿主；接入登录组件并不自动隔离所有业务数据。开发预览提供A/B账号的真实读写隔离实验，参见[演示说明](docs/demo.md#user-isolation)。
