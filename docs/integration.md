# 接入与安全边界

## 选择接入层级

| 需求 | 入口 | 网站保留的责任 |
| --- | --- | --- |
| 新站直接获得登录页 | `FastAPIAuth(..., ui=LoginUI(...))` | 用户来源、业务路由、部署与 TLS |
| 自有品牌和样式 | `LoginUI(template_dirs=..., template_name=...)` 或 `renderer` | 自定义 HTML/CSS、renderer 内容安全 |
| 已有 HTML/JS 前端 | `FastAPIAuth(..., ui=None)` | 原页面、前端状态与所有业务数据 |
| 保持已有 HTTP/数据库契约 | `CallbackBackend` + `SessionManager` + 宿主 `SessionStore` | 原账号 ID、密码材料、数据库/会话映射、响应兼容 |

Headless 不等于另起认证微服务。可以在同一个 FastAPI 进程挂载 JSON 路由，也可以只调用核心 Python API，保留既有 HTTP handler 与 JSON 字段。普通 Python 包即可携带 HTML/CSS/JS；安装位置不是定制入口，宿主模板目录优先于包内模板。

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
- 内存 store 有容量上限，仅用于单进程演示/测试。SQLite 是持久本地方案；多主机部署需提供共享的 `SessionStore`。登录频率限制是进程级后备保护，不是分布式抗滥用服务。
- `origin` 应是部署的固定可信源；不从任意 Host 或 forwarded 头自动推断。反代信任、TLS 与宿主服务进程由网站负责。

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
