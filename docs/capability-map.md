# 能力地图

## 已实现能力

| 能力 | 状态 | 边界 |
| --- | --- | --- |
| 身份与授权 | 已实现 | `Principal`、`Role`、401/403、`require_role`、`require_owner`；admin 不自动绕过 owner |
| 认证后端 | 已实现 | `PasswordBackend` 支持一个或多个显式账号；`CallbackBackend` 接入宿主用户库 |
| ChatVoice 兼容后端 | 已实现（核心包，按需导入） | `ChatVoiceAuth` / `ChatVoiceSessionStore`；仅现有 ChatVoice schema、固定命名空间与 USER，不建表/迁移，无 ChatVoice/web 依赖 |
| 旧密码材料校验 | 已实现 | `verify_pbkdf2` 可验证宿主已有的 PBKDF2-HMAC-SHA256 salt/digest，不强制改密码 |
| 会话 | 已实现 | opaque token、仅存 SHA-256、TTL、轮换、撤销、CSRF secret；内存 store 仅用于测试/演示 |
| SQLite store | 已实现 | 按实例命名空间隔离，数据库文件 `0600`，新建私有目录且不 chmod 共享父目录 |
| FastAPI adapter | 已实现（`web` extra） | 可配置前缀、cookie、Origin/Host、请求体限制、限流、JSON/headless 路由和依赖 |
| 默认登录 UI | 已实现（`web` extra） | `indigo/forest/amber` 色系与 `card/split` 布局，包内模板/CSS/JS 可从 wheel 读取 |
| 宿主模板覆盖 | 已实现 | 模板目录优先、区块继承、整页 renderer、本地自定义 stylesheet |
| ChatEnv 命名空间 | 已实现 | 保留 `ChatLogin` typed profile；本版本不新增 API key 字段 |

## 接入选择

1. **新网站**：默认 UI + `PasswordBackend` 或宿主回调即可起步。
2. **需要自有视觉**：保留 FastAPI adapter，替换 `LoginUI` 的模板目录、模板名或 renderer。
3. **已有 ChatVoice schema**：直接选用 `ChatVoiceAuth`；保留原 HTTP/前端，或将 `backend` / `manager` 交给通用 FastAPI adapter。默认 UI、宿主覆盖和 headless 均可使用。

后端选择：固定/多账号 `PasswordBackend`；其他宿主库 `CallbackBackend` + 宿主 `SessionStore`；ChatVoice schema 用现成 `ChatVoiceAuth`。详见 [选择矩阵](integration.md)。

## 不在当前范围

- 不提供独立常驻登录服务、SSO、OAuth/邮箱登录、MFA 或账户管理后台。
- 不接管会议、文件、卡片等业务数据；每个宿主继续定义资源 owner 和 policy。
- 不把 guest 当成数据库账户；访客体验由宿主显式声明。
- 不提供万能 ORM 或后端注册中心；ChatVoice 兼容后端来自自有桥接实现，并以旧 schema 合成测试验证。
- 不输出 secret、cookie、CSRF token、Authorization header 或生产凭据。
