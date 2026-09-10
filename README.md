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
| FastAPI 快速接入 | [Python 接口树](docs/interface-tree.md) |
| 默认 UI、模板覆盖与 headless | [能力地图](docs/capability-map.md) |
| CLI 版本和命令树 | [CLI 树](docs/cli-tree.md) |

## 安装

```bash
pip install "ChatLogin[web]"
```

核心包不要求网站采用包内页面。已有静态 HTML/原生 JS 的网站可以只挂载 JSON 路由，继续保留原登录入口和用户数据库。

## 选择认证后端（0.1.2）

| 账户来源 | 可选后端 | 会话与宿主边界 |
| --- | --- | --- |
| 固定账号 / 多个显式账号 | `PasswordBackend(accounts)` | 一个 / 多个哈希条目；搭配 `SessionManager` 与所选 store |
| 其他宿主用户库 | `CallbackBackend(authenticate)` + 宿主 `SessionStore` | 宿主定义密码验证、schema 和会话映射 |
| 已有 ChatVoice 账户/会话 schema | `chatlogin.backends.ChatVoiceAuth` | 现成兼容后端；固定 `chatvoice` 命名空间，不建表或迁移 |

`ChatVoiceAuth` 随核心包提供，按需导入；不依赖 ChatVoice 包或 `web` extra，不是任意 SQLite 账户系统的通用 ORM。默认 UI、宿主覆盖和 headless 三种模式与后端选择相互独立。账户创建、业务 owner 权限与宿主 HTTP 契约仍由网站负责。见 [接入与安全](docs/integration.md)。

## 设计边界

- `guest` / `user` / `admin` 是服务端可信身份，角色不能由请求体指定。
- 固定账号、多账号和宿主回调均可；已有 PBKDF2 密码材料可验证，不强制迁移。
- 会话 token 只以 SHA-256 摘要持久化，支持 TTL、轮换、撤销、CSRF 和实例隔离。
- FastAPI adapter 默认同站 Origin/Host 校验、请求体大小限制、限流和安全 `next`。
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

可运行的 FastAPI 合成账号示例：`examples/demo_fastapi.py`。
