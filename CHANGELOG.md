# 更新日志

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
