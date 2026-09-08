# ChatLogin 文档

ChatLogin 把网站登录中的**后端安全契约**做成可复用 Python 能力，同时把前端外观留给宿主网站：可以用包内默认登录页，也可以只覆盖模板/CSS，还可以完全保留宿主原生 HTML/JS，以 headless 方式调用 JSON 接口。

站点入口：<https://arch.gh.wzhecnu.cn/ChatLogin/>

## 按场景选择文档

<div class="grid cards" markdown>

- **快速接入 FastAPI**

    安装 `web` extra，挂载可配置前缀的认证路由、依赖和默认页面。

    [查看接口树](interface-tree.md)

- **保留现有网站样式**

    默认模板、宿主模板覆盖、headless JSON 三种接入层级；ChatVoice 首个集成验收走 headless。

    [查看能力边界](capability-map.md)

- **校对 CLI 与包边界**

    CLI 只负责版本和标准命令树；认证能力首先是可 import 的 Python API。

    [查看 CLI 树](cli-tree.md)

</div>

## 安装

```bash
python -m pip install "ChatLogin[web]"
```

最小 FastAPI 集成使用合成账号或宿主提供的回调，不内置默认生产密码：

```python
from fastapi import Depends, FastAPI
from chatlogin import CallbackBackend, MemorySessionStore, Principal, SessionManager
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

def verify(username: str, password: str) -> Principal | None:
    return Principal("usr_1", "Synthetic user") if (username, password) == ("one", "secret") else None

auth = FastAPIAuth(
    CallbackBackend(verify),
    SessionManager(MemorySessionStore(), instance="my-site"),
    origin="https://www.example.com",
    prefix="/api/auth",
    ui=LoginUI(title="My site"),
    cookie=CookieSettings(name="my_site_session"),
)
app = FastAPI()
app.include_router(auth.router)

@app.get("/private")
def private(principal=Depends(auth.current_user)):
    return principal.as_dict()
```

完整可运行示例见仓库 `examples/demo_fastapi.py`，仅使用临时合成账号。

## 前端三种接入

| 层级 | 适用场景 | 安全边界 |
| --- | --- | --- |
| 默认 UI | 新站快速开始 | 包提供 HTML/CSS/JS、主题和布局；后端仍统一签发 opaque cookie |
| 宿主覆盖 | 希望品牌、局部区块或整页融入原站 | 通过 Jinja `ChoiceLoader`、区块继承、自定义 CSS 覆盖；不修改 site-packages |
| Headless | ChatVoice 这类已有静态 HTML/原生 JS 的网站 | 不加载默认页面和资源，只调用 `/login`、`/session`、`/logout` JSON 契约 |

样式只影响展示，不改变认证、CSRF、cookie、角色或资源 owner 校验。默认资源使用 scoped `.chatlogin` 类与 CSS variables，不全局重置宿主页面。

## 安全默认值

- 服务端可信身份：`guest`、`user`、`admin`；登录请求不能自行提升角色。
- 密码校验后端可注入；支持固定账号、多账号和宿主回调，兼容已有 PBKDF2 材料但不强制迁移。
- 会话 token 使用安全随机值，数据库仅保存 SHA-256 摘要；支持到期、轮换、撤销和实例隔离。
- Cookie 默认 `HttpOnly`、`Secure`、`SameSite=Lax`；写操作需要同站 Origin 与 CSRF token。
- `next` 只允许站内绝对路径；登录请求体有长度限制和固定窗口限流。
- 角色不绕过资源 owner 检查，Admin 也不自动获得他人业务数据。

英文首页：<https://arch.gh.wzhecnu.cn/ChatLogin/en/>。
