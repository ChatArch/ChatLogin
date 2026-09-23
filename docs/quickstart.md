# 快速接入自己的项目

<div class="grid cards" markdown>

- **新建 FastAPI 网站**：复制下方完整应用，先完成一次真实登录。
- **已有账户数据库**：保留账户与密码材料，换用 [同步或异步回调](integration.md#backends)。
- **已有前端**：保留页面，只挂载 `ui=None` 的 JSON 接口，按 [浏览器契约](integration.md#browser-contract) 传递会话与 CSRF。
- **先选视觉风格**：运行 [演示站](demo.md) 的模板游乐场，再复制 `LoginUI(...)` 配置。

</div>

## 1. 安装并保存完整应用

```bash
python -m pip install "ChatLogin[web]" uvicorn
```

把下面代码保存为 `app.py`。账号名为 `operator`，密码必须由你显式设置；示例不会读取演示站账号，也没有默认生产密码。

```python
"""Minimal host app; provide an explicit password through the environment."""
import os
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI
import uvicorn
from chatlogin import MemorySessionStore, PasswordBackend, Principal, SessionManager, hash_password
from chatlogin.fastapi import CookieSettings, FastAPIAuth
from chatlogin.ui import LoginUI

origin = os.environ.get("MY_SITE_ORIGIN", "http://127.0.0.1:8000")
password = os.environ["MY_SITE_LOGIN_PASSWORD"]
backend = PasswordBackend({
    "operator": (Principal("operator", "Operator"), hash_password(password)),
})
app = FastAPI()
auth = FastAPIAuth(
    backend,
    SessionManager(MemorySessionStore(max_sessions=256), instance="my-site", ttl=3600),
    origin=origin,
    ui=LoginUI(),
    cookie=CookieSettings(secure=urlsplit(origin).scheme == "https"),
)
app.include_router(auth.router)

@app.get("/")
def home():
    return {"login": "/auth/?next=/private"}

@app.get("/private")
def private(user=Depends(auth.current_user)):
    return user.as_dict()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, proxy_headers=False)
```

## 2. 显式设置密码并启动

在 Bash/Zsh 终端输入下面命令，再输入不少于 12 个字符的测试密码。输入不回显，密码不会进入命令行参数。

```bash
read -rs MY_SITE_LOGIN_PASSWORD
export MY_SITE_LOGIN_PASSWORD
python app.py
```

打开 <http://127.0.0.1:8000/auth/?next=/private>，使用 `operator` 与刚设置的密码登录。成功后 `/private` 返回服务端可信用户信息；未登录直接访问该路径返回 401。

这个示例使用单进程内存会话，重启即清空。生产部署应选择持久化 store、固定 HTTPS origin 和符合业务的数据权限；不能把公开演示身份搬进真实网站。

## 3. 保留后端，独立选择前端

| 你希望保留什么 | 修改方式 | 宿主负责什么 |
| --- | --- | --- |
| 直接使用默认 UI | `ui=LoginUI(palette="forest", layout="split")` | 账户来源、业务路由 |
| 自有模板与品牌 | `LoginUI(template_dirs=("templates",), template_name="host/login.html")` | 模板安全、静态资源 |
| 原有 HTML/JS | `ui=None` | 表单、错误反馈、登录后的跳转 |
| 标准库 HTTP 宿主 | `LoginUI.render(context)` | Cookie、Origin、CSRF 与 HTTP 路由 |

`template_dirs` 是宿主可信模板目录，必须存在；不要修改 site-packages。模板覆盖和回调账户库互相独立。`script_url` 可指定同源本地脚本，默认不加载宿主脚本。

## 4. Headless 请求顺序

1. `GET /auth/session`，匿名时也返回 200 与 `authenticated=false`。
2. `POST /auth/login`，JSON 包含 `username`、`password`、`next`。浏览器自动发送同源 Origin；如果已有有效会话，先读取当前 CSRF，并加入 `X-CSRF-Token`。
3. 使用 `credentials: 'same-origin'` 调用业务接口；Cookie 自动携带，不要手工读取 token。
4. 写操作使用当前 CSRF；退出前重新读取 session，再 `POST /auth/logout`。
5. 退出后清理私有界面；受保护接口恢复 401。

完整可运行的前端实现可以查看包内 `chatlogin.demo_site/assets/demo.js` 的 Headless 演示。公开 Demo 的业务数据是合成数据，不代表你的后端已经接入。

## 下一步

- [接入与安全](integration.md)：四类后端、精确 ChatVoice schema、HTTP/角色/owner 边界。
- [Python 接口树](interface-tree.md)：可导入的类与实际方法。
- [演示站](demo.md)：启动独立演示和查看配置效果。
