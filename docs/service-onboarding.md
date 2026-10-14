# 新服务接入：统一账号 HTTP 契约

ChatLogin 0.2.1 把账号接口和页面作为**每个服务自己的插件**挂载。一次 `create_managed_auth` 可得到登录、会话、本人资料和用户管理；宿主选择齿轮、普通链接或自有前端，不复制认证实现。这不是共享 Cookie 的 SSO、集中身份服务或任意外部用户库的通用 CRUD。

## 从空服务到可登录页面

```bash
python -m pip install "ChatLogin[web]==0.2.1" uvicorn
```

先在受保护的进程环境中提供 `MY_SERVICE_BOOTSTRAP_PASSWORD`，再初始化空实例。命令行只接收变量名，不接收密码值；没有生产默认账号或自动注册。

```bash
chatlogin users bootstrap operator --instance my-service --password-env MY_SERVICE_BOOTSTRAP_PASSWORD
```

把 [完整 factory](https://github.com/ChatArch/ChatLogin/blob/main/examples/managed_service.py) 保存为 `auth_app.py`，再建立 `app.py`：

```python
import os
from auth_app import create_app
from chatlogin.account_ui import AccountMenuUI

app = create_app(
    instance="my-service",  # 与 bootstrap 相同
    origin=os.environ["MY_SERVICE_ORIGIN"],
    prefix="/auth",         # 也可 /admin；不影响角色策略
    menu_ui=AccountMenuUI(mode="gear"),
    allow_insecure_loopback=os.environ.get("MY_SERVICE_ALLOW_LOOPBACK") == "1",
)
```

部署使用浏览器真正访问的固定 HTTPS origin，由宿主负责 TLS／反代：

```bash
MY_SERVICE_ORIGIN=https://service.example.com python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

仅在本机开发时显式开启 loopback HTTP：

```bash
MY_SERVICE_ORIGIN=http://127.0.0.1:8765 MY_SERVICE_ALLOW_LOOPBACK=1 python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

打开首页 → 齿轮“账号设置” → 登录；owner/admin 登录后可进入用户管理，普通用户只进入本人资料。示例还提供 `/private` 的 `auth.current_user` 和 `/operator` 的明确角色依赖。业务数据仍需 `require_owner` 或宿主 ACL，admin/owner 不自动读取他人的业务记录。

factory 自建的 store 在 ASGI shutdown 关闭。测试或共享同进程服务可显式注入 `users`；注入对象由调用方拥有并负责关闭，不因一个宿主退出而被销毁。它不会迁移既有账户或读取演示默认凭据。

## 统一的 API 发现入口

`GET /auth/api` 返回 `version`（安装包版本）、`schema_version=1`（发现格式）、`operations`（实际注册的 HTTP 方法和路径）、`pages`（存在的页面）和 `capabilities`（login/managed_users/profile）。`prefix="/admin"` 时入口为 `/admin/api`；可信 ASGI mount 也计入 URL，忽略任意 forwarded-prefix 头。

发现接口验证 Host、返回 `no-store`，不返回用户目录、Cookie、CSRF、凭据或 state 路径。它描述**功能是否提供**，不代表当前用户有权限。固定账号／callback 不虚报用户管理；`pages=False` 的页面表为空。

### 默认 HTTP 契约

以下路径均相对 `/auth`（或宿主选择的前缀）。会话身份由服务端解析，绝不从请求的 actor/role 字段获得管理员权限。

| 方法与路径 | JSON／结果 | 权限 |
| --- | --- | --- |
| `GET /api` | 发现信息 | 可信 Host，可匿名 |
| `GET /session` | authenticated、user、csrf_token | 可信 Host；匿名也返回 200 |
| `POST /login` | username、password、可选 next | 同源；已有会话还需当前 CSRF |
| `POST /logout` | 撤销会话 | 登录、同源、CSRF |
| `GET /api/users?offset=0&limit=100` | 安全用户列表；limit≤100 | owner/admin，范围由后端策略限制 |
| `POST /api/users` | username、password、可选 display_name/role；201 | owner/admin；只有 owner 可授予 admin |
| `GET /api/users/{user_id}` | 用户安全元数据 | owner/admin 的可管理范围 |
| `PATCH /api/users/{user_id}` | display_name、role、enabled 的合法组合 | 对象级权限、同源、CSRF |
| `DELETE /api/users/{user_id}` | deleted | 对象级权限、同源、CSRF；禁止删 owner |
| `POST /api/users/{user_id}/password` | new_password | 对象级权限、同源、CSRF |
| `GET /api/profile` | 本人用户资料 | 当前登录用户 |
| `PATCH /api/profile` | display_name | 本人、同源、CSRF |
| `POST /api/profile/password` | current_password、new_password | 本人、同源、CSRF；旧会话失效 |
| `POST /api/owner/transfer` | target_user_id、current_password、confirm_username | owner 复验、同源、CSRF、原子交接 |

浏览器 `credentials: 'same-origin'`，从 `/session` 读取当前 CSRF，在写操作 `X-CSRF-Token` 头发送；不要把密码、Cookie 或 CSRF 写入 localStorage、URL 或日志。常见错误为 400（非法请求／Host）、401（未认证）、403（权限／Origin／CSRF）、404（对象不存在）、409（状态冲突）、413（体上限）、429（限流）、503（受控容量／服务不可用）。发现目录不是完整请求／响应 Schema，也不替代上述契约和宿主 OpenAPI。

## 齿轮、普通链接与 DIY

```python
from chatlogin.account_ui import AccountMenuUI

# 宿主 async GET handler 内；request 为真实 FastAPI Request。
menu = await auth.render_account_menu(request)  # 中文、原生齿轮浮层
menu = await auth.render_account_menu(request, ui=AccountMenuUI(mode="links"))
menu = await auth.render_account_menu(request, ui=AccountMenuUI(language="en"))
# 自有模板或可信 renderer：
menu = await auth.render_account_menu(
    request, ui=AccountMenuUI(template_dirs=["templates"], template_name="account/menu.html")
)
# 完全 DIY：只拿安全导航信息，自行渲染。
navigation = await auth.navigation_from_request(request)
```

宿主承载当前身份的 HTML 响应也需设置 `Cache-Control: no-store`，不要由 CDN 或共享缓存保存用户菜单。导航从真实当前 session 解析 identity/role/links/assets_path；改密、禁用或角色变化后旧会话不继续提供管理入口。菜单不依赖 JS 初始化；CSS 仅作用于自身，并继承宿主字体和 ChatLogin 色板。默认片段自动转义身份／标签并验证本地链接，renderer 的 HTML 安全由可信宿主负责。退出仍是现有页面中的受 CSRF 保护 POST，不提供 GET 退出链接。

`pages=False` 保留 JSON API、没有默认 HTML/assets；默认菜单也不生成假的空设置按钮。自有前端按同一 HTTP 契约工作。`LoginUI`、`UserAdminUI`、`UserProfileUI` 保持独立模板／renderer 覆盖，安装位置不应被手动修改。

已有用户库应选择 [适配路径](integration.md)：callback 只认证，不自动接管账户生命周期；ChatVoice legacy schema 使用明确保留式 adapter。统一 HTTP 契约不等于统一账号库、共享 Cookie 或跨站 SSO。
