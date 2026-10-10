# ChatVoice legacy schema 集成

!!! warning "未发布预览"
    本页描述候选 provider/consumer 配对能力。公开的 ChatLogin 0.1.6 与 ChatVoice 0.4.1 不一定包含这些新 API；预览环境应使用已审查的匹配 wheel 对。稳定安装在匹配发布后再按正式版本约束采用。

该集成面向已经使用 ChatVoice/Speakr SQLite `accounts` 与 `auth_sessions` 的宿主。目标是保留原账号、密码材料、会话表关系、业务 `owner_id`、API token 归属、会议/对话/录音等数据，同时把同一账户目录暴露给 ChatLogin managed users 的 owner/admin/user 管理能力。

## 支持的 schema 采用方式

```python
from chatlogin.backends import (
    ChatVoiceManagedStore,
    adopt_owner,
    initialize_chatvoice_managed_schema,
)
from chatlogin.managed import ManagedUsers

store = ChatVoiceManagedStore(connect, lock, clock, max_users=10000, max_sessions=10000)
store.initialize()
users = ManagedUsers(store, session_namespace="chatvoice", ttl=86400, clock=clock)

owner = adopt_owner(store, "admin@example.invalid")
```

`connect`、`lock` 与 `clock` 由受信任同进程宿主提供，并指向同一个 ChatVoice 数据库和互斥边界。`initialize_chatvoice_managed_schema(connection)` 可在宿主的显式数据库 setup 中调用；迁移不是 import side effect，也不是公开 HTTP bootstrap。

## 数据保留

| 原始数据 | 集成后的处理 |
| --- | --- |
| `accounts.id` | 继续作为稳定 `user_id`；不重建、不重新分配 |
| `account` / `display_name` | 作为 managed username/display name 的来源 |
| `password_salt` / `password_hash` | 原字节保留；不重新哈希旧密码 |
| 业务表 `owner_id` | 继续指向原稳定账号 ID；managed `OWNER` 不是业务记录通行证 |
| `auth_sessions` | 继续由同一 cookie/session 关系解析；角色、状态或密码安全变化会使受影响旧会话失效 |
| API token | 禁用或删除账号后拒绝访问，不删除保留行 |

schema 初始化是显式、幂等、additive 的：为旧账号补充 role/status/revision 等管理列，默认旧账号为 enabled `USER`，并建立唯一有效 owner 约束。它不删除旧行、不复制账号到第二个用户库，也不改写业务归属。

## 账号匹配规则

启用 managed schema 后，`ChatVoiceAuth` 与 `ManagedUsers` 共用 `lower(account)` 账号键：ASCII 账号大小写变体可登录同一既有身份，原 `account` 字符串、ID、盐和密码哈希不改写。规范化键冲突时拒绝认证，不能选择任意匹配行；schema 初始化也会拒绝冲突，并在原表建立规范化唯一性约束。尚未启用管理元数据的旧库继续采用原来的精确账号匹配。

## Owner 采用

`adopt_owner(store, exact_existing_account_or_id) -> UserRecord` 只用于一次性采用精确既有账号或 ID：

- 已存在 owner 时失败。
- 目标必须已在原 `accounts` 中存在。
- 采用会把该账号设为 enabled `OWNER`，递增认证 revision，并返回不含凭据的 `UserRecord`。
- 其他既有账号保持 `USER` / enabled，除非后续由 owner/admin 通过管理 API 修改。

示例中的 `admin@example.invalid` 是合成占位账号。生产选择由宿主的受信任 Python setup 执行，不在公共文档、命令历史或日志中写入真实账号、用户 ID、哈希或 token。

## 权限与信任边界

| 边界 | 说明 |
| --- | --- |
| 公开注册 | 不提供。ChatVoice 原生账号仍由 invite-only/受信任工具创建 |
| 宿主连接 | `connect`/`lock` 是同进程受信任接口；不防御恶意 in-process 代码 |
| 管理角色 | owner/admin/user 管理账户目录；业务会议、音频、API token、模型调用仍需宿主 ACL |
| owner 含义 | `OWNER` 是账号目录 owner，不是所有业务数据的全读权限 |
| 会话失效 | 角色、状态、删除、改密和 owner 交接通过 revision 使受影响会话失效 |
| owner 交接 | 由 managed users 的 owner-only 原子交接处理 |

宿主仍需在业务路由中执行原来的记录归属检查，例如会议 `owner_id`、声音任务所属账号、只读 token scope 与禁用/删除账号拒绝策略。

