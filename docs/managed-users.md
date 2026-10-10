# 托管用户

本页说明计划随 `0.2.0` 提供的托管用户预设。新接入方应显式声明 `ChatLogin>=0.2.0,<0.3.0`；已使用固定账号、回调或 ChatVoice 兼容后端的应用不必改变。ChatVoice 既有消费者的 `<0.2` 依赖保持不受影响，只有主动采用托管用户时才升级和接入。

## 先选择合适的入口

| 需求 | 入口 | 账户与业务边界 |
| --- | --- | --- |
| 应用需要自己的 owner/admin/user 账户、登录页、本人资料与用户管理 | `ManagedUsers` + `create_managed_auth` | ChatLogin 管理该实例的账户与会话；宿主仍管理业务数据授权 |
| 账号已在宿主或上游系统 | `CallbackBackend` / `AsyncCallbackBackend` | 宿主继续管理账户、密码材料与生命周期 |
| 少量显式固定账号 | `PasswordBackend` | 账户条目由宿主配置 |
| 保持既有 ChatVoice schema | `ChatVoiceAuth` | 兼容层不创建或迁移账户表 |

托管用户是可选预设，不会自动迁移旧用户数据库、不会把旧后端转换为新数据库，也不是 SSO、OAuth 或 MFA。它也不把 `owner`、`admin` 解释为宿主业务数据的通行证；业务路由仍应执行自己的 `require_owner(user, record.owner_id)` 或等价授权。


## 作为插件集成 {#plugin}

ChatLogin 不拥有业务应用的服务器，也不要求额外建设登录微服务。应用安装依赖、选择账号后端并挂载插件；登录、身份、会话、CSRF、角色及默认页面由同一组件复用。宿主仍决定业务记录、下载、任务和数据归属的授权。

| 集成方式 | 配置 | 复用机制 |
| --- | --- | --- |
| 默认页面 | `create_managed_auth(..., pages=True)` | 登录、用户管理、本人账号模板与全部受保护接口 |
| 自有前端 | `create_managed_auth(..., pages=False)` | 只注册会话／登录／退出及账号管理接口，不注册包内 HTML 或 assets |
| 已有账号库 | 现有 backend + `FastAPIAuth`／核心库接口 | 保留数据库和密码材料，复用会话与安全检查；不会自动接管旧库的账号生命周期 |

```python
auth = create_managed_auth(
    instance="mytool",
    origin="https://app.example.com",
    pages=False,  # 保留应用自己的登录和管理前端
)
app.include_router(auth.router)
```

已有消费者不必复制哈希、会话、CSRF 或权限校验实现；但现有 callback/ChatVoice/Dufs 等适配账户不会被自动迁入托管目录。其他 HTTP 宿主可直接组合 `ManagedUsers`、`SessionManager` 与安全检查；非 Python 前端调用宿主已挂载的同源接口，这不等于 OAuth／跨站 SSO SDK。

## 最小挂载

先由显式操作员创建该实例的第一个 owner，再启动 Web 应用。密码值只存在于环境中；命令行接收的是环境变量**名称**，不是密码：

```bash
# 在安全的进程环境中提供 APP_BOOTSTRAP_CREDENTIAL；不要把值写进命令历史。
chatlogin users bootstrap operator \
  --instance mytool \
  --password-env APP_BOOTSTRAP_CREDENTIAL \
  --display-name "Operator"
```

该命令只允许空的账户实例进行首次 bootstrap。重复 bootstrap、不安全状态路径或无效输入会非零失败；没有 `--force`、chmod 修复或自动确认。`--home` 仅在需要显式 ChatArch home 时传入，`--json` 只输出安全的 `UserRecord` 字段，绝不输出凭据、哈希、cookie 或 CSRF。

应用的最小 FastAPI 挂载如下：

```python
import os

from fastapi import Depends, FastAPI
from chatlogin.managed_web import create_managed_auth

app = FastAPI()
auth = create_managed_auth(
    instance="mytool",
    origin=os.environ["MYTOOL_ORIGIN"],
)
app.include_router(auth.router)

@app.get("/private")
async def private(user=Depends(auth.current_user)):
    return {"user_id": user.user_id}
```

需要显式拥有服务对象（例如测试或自定义生命周期）时，先创建再传入同一个实例：

```python
from chatlogin.managed import ManagedUsers
from chatlogin.managed_web import create_managed_auth

users = ManagedUsers.for_instance("mytool")
auth = create_managed_auth(instance="mytool", origin="https://app.example", users=users)
```

`ManagedUsers.for_instance(instance, home=None, ...)` 使用该账户实例受控的持久存储。`ManagedUsers.in_memory(instance, ttl=300, max_users=..., max_sessions=...)` 只用于显式测试或演示；它不读取 profile/home，也必须在应用 shutdown 时关闭其生命周期。

## 角色与操作

| 操作 | owner | admin | user |
| --- | --- | --- | --- |
| 登录、查看/修改本人资料、修改本人密码 | 是 | 是 | 是 |
| 用户管理页与列表 | 全部安全元数据 | 普通用户及本人 | 否 |
| 创建普通用户 | 是 | 是 | 否 |
| 创建或授予 admin | 是 | 否 | 否 |
| 停用、删除、重置普通用户密码 | 是 | 是 | 否 |
| 管理其他 admin | 是 | 否 | 否 |
| 直接停用、删除或降级 owner | 否 | 否 | 否 |
| owner 交接 | 显式目标用户名确认、当前密码复验、原子交接 | 否 | 否 |

每个账户实例只有一个有效 owner。交接会使旧 owner 与目标用户的会话失效；角色、状态、删除和改密也会使受影响账户的旧会话失效。不要把应用自己的记录所有权混入这一角色表：`require_owner` 仍是宿主拥有的业务规则。

## Web、模板与 headless

`create_managed_auth(...)` 返回 `ManagedAuth`，提供 `.router`、`.users`、`.current_user`、`.csrf_user`、`.admin_user` 和 `.cookie`。默认挂载前缀为 `/auth`：

| 路径 | 用途 |
| --- | --- |
| `/auth/` | 登录页 |
| `/auth/users` | 用户管理页 |
| `/auth/profile` | 本人资料页 |
| `/auth/api/users` | 用户列表、创建与用户管理 API |
| `/auth/api/profile` | 本人资料和改密 API |
| `/auth/api/owner/transfer` | owner 交接 API |
| `/auth/session`、`/auth/login`、`/auth/logout`、`/auth/assets` | 继承的会话、登录、退出和静态资源接口 |

默认 `LoginUI`、`UserAdminUI` 与 `UserProfileUI` 使用同一主题、色板与外观约定。可信宿主可覆盖相应模板或 renderer；`headless` 接入则保留宿主页面并调用受保护 API。无论页面怎么替换，后台仍执行 Host/Origin、会话、CSRF 和角色校验。

账户与会话的**目录/实例命名空间**由 `instance` 决定；`origin` 是浏览器 Host/Origin 校验和 cookie 安全配置，不能用 URL、proxy 头或请求体来选择账户库。挂载在子路径时，生成的 UI 与静态资源 URL 仍使用受信任的 mount/root path。

## 独立合成演示

安装 `demo` extra 后可启动独立的真实预设演示：

```bash
chatlogin serve --managed-demo
```

它用 `ManagedUsers.in_memory(...)` 创建三组明确标记为公开合成的 owner、admin 与 user 账号，并通过真实 `bootstrap_owner`、`authenticate` 和 `create_user` 构建身份。演示不会读取用户 home/profile、生产账号库或生产会话；`/health` 只返回版本、`managed-demo` 模式和合成标记，公开 fixtures API 也只返回刻意公开的合成账号值。默认 `chatlogin serve` 继续是原有的四后端演示，行为不变。

## 迁移与安全边界

- 没有旧用户库的自动迁移，也不删除或改写宿主业务数据。
- 没有 SSO、OAuth、MFA、邮件、短信或扫码认证声明。
- 固定账号、回调和 ChatVoice adapter 的账户管理职责仍在宿主；它们不会因此获得托管用户管理页。
- 生产部署仍由宿主管理固定 HTTPS origin、TLS、反向代理、服务进程和业务授权。
- 只将 `--password-env` 指向受控环境变量，勿记录其值、cookie、CSRF、密码哈希或 session token。
