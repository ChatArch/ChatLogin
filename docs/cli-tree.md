# CLI 树

认证与网页功能由 [Python 接口](interface-tree.md) 提供。命令行提供版本查询和无副作用的路径回读，不另起登录服务。

## 顶层命令

```text
chatlogin
├── --help                                      # 查看帮助
├── --version                                   # 查询安装版本
├── --tree                                      # 真实命令树，含参数
├── --tree-brief                                # 简明命令树
└── paths <INSTANCE> [--home HOME] [--json]      # 只读解析实例运行路径
```

## 路径检查

```bash
chatlogin paths my-site --json
chatlogin paths my-site --home "$HOME/.chatarch" --json
```

返回 `directory` 与 `database` 字段。显式 `--home` 优先于 ChatEnv 的默认 home；路径支持用户目录和已定义环境变量，拒绝未知变量与不安全实例名。此命令不创建目录、数据库或账户。

## 验证命令

```bash
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
```

命令树直接来自 ChatStyle 和 Click 已注册元数据；新增命令时同步更新测试和本页。网页接入见 [接入与安全](integration.md)。
