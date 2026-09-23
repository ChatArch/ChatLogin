# 更新日志

## 0.1.4 — 2026-09-23

- 新增稳定导出的 `PrivateSQLite` 复用原语，`SQLiteSessionStore` 改为委托它管理私有目录、真实路径 `mode=rw` 连接和事务；保留既有 store API、schema 与会话行为，供依赖 ChatLogin 的叶子包复用。
- POSIX 下逐级 no-follow 校验祖先：可改名后代的目录必须由 root（含用户命名空间映射）或服务 UID 拥有，且不得由不受信任的 group/other 写入；仅在 sticky 语义能保护可信 owner 条目时接受例外，最终数据目录必须由服务 UID 拥有且恰为 `0700`。
- 已有数据库与 `-journal`/`-wal`/`-shm` 必须是服务 UID 拥有、单链接、恰为 `0600` 的普通文件，绝不通过 chmod “修复”历史路径；只为新建私有目录/主库显式设 mode，并仅在可信 `0700` 目录内规范化本次连接新建且类型、owner、链接数安全的 sidecar。
- SQLite 以真实数据库路径打开，不再使用或宣称 `/proc/self/fd` / `/dev/fd` alias 能保护 sidecar。安全边界不排除同 UID 进程；非 POSIX 保留隔离的旧兼容路径，且不声称 POSIX no-follow/mode 等价于平台 ACL。

## 0.1.3 — 2026-09-11

- 新增 `AsyncCredentialBackend` 协议与 `AsyncCallbackBackend`，复用同步 `CallbackBackend` 的用户名/密码字节上限和受信任 `Principal` 校验；非法输入不会调用宿主回调，非法返回值失败关闭。
- `SessionManager.purge_expired()` 成为公开 API，通过当前 manager 的已验证 instance 与 clock 委托给 store，不改变 issue/resolve/revoke 语义。
- 新增 `ui` optional dependency group，仅包含有界 `Jinja2`；`web` extra 继续包含 FastAPI/Starlette/Jinja2 完整栈，核心导入保持轻量。
- 基于跨版本兼容性测试，将 `web`/`dev` 的 Starlette 窗口扩展为 `starlette>=0.40,<2.0`；测试覆盖 Starlette 0.x、`FastAPI==0.133.1` + `Starlette==1.3.1`、`FastAPI==0.141.1` + `Starlette==1.6.0`。
- `dev` extra 为 Python 3.10 测试加入有界条件依赖 `tomli>=2.0,<3.0; python_version<"3.11"`；运行时核心依赖不包含 tomli。
- 文档补充异步宿主验证、标准库 HTTP + `LoginUI`、会话清理和兼容性门禁边界。

## 0.1.2 — 2026-09-11

- 将自有 ChatVoice 认证桥接提升为内建可选 `ChatVoiceAuth` / `ChatVoiceSessionStore`，核心包可直接导入，无需 ChatVoice 或 web 依赖。
- 保持既有账户/会话 schema、310000 次 PBKDF2、ISO expiry、旧 CSRF、token 摘要、动态回调、原子轮换与容量边界，不建表或迁移。
- 补齐合成旧 schema、并发容量、回滚、角色/命名空间隔离与三种 UI 接入模式回归；通用 FastAPIAuth / LoginUI 安全行为不变。
- 中英文文档增加固定/多账号、宿主回调、现成 ChatVoice 后端选择矩阵和薄接入示例。

## 0.1.1 — 2026-09-09

- 新增可复用身份、认证、会话、CSRF、回跳与 FastAPI headless adapter。
- 新增默认登录页、主题/布局选项、宿主模板覆盖和静态资源打包。
- 记录 ChatVoice 保留原前端接入的边界，为后续验收 patch 准备。

## 0.1.0 — 2026-09-09

- 发布初始模板，提供版本、帮助、完整与简明 CLI 树。
- 提供 ChatEnv 配置扩展入口及中英文接口文档。
- 使用 Tag 与 PyPI Trusted Publisher 自动发布。
- 本版本不包含登录、用户管理或鉴权业务。

## 0.0.1 — 2026-09-09

- 建立 ChatArch 标准 Python 包与 PyPI 占位版本。
- 提供版本、帮助、完整 CLI 树和简明 CLI 树。
- 保留无业务字段的 ChatEnv 配置扩展入口。
- 登录、用户管理和鉴权功能尚未实现。
