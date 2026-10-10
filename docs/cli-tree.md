# CLI 树

可复用认证与网页能力由 [Python 接口](interface-tree.md) 提供。命令行还可运行隔离产品演示；它不是生产登录微服务。

## 顶层命令

```text
chatlogin
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── paths <INSTANCE> [--home HOME] [--json]  # Show instance runtime paths without creating files or directories.
├── serve [--host HOST] [--port PORT] [--origin ORIGIN] [--managed-demo]  # Serve the isolated synthetic product demonstration.
└── users  # Explicit managed-user lifecycle operations.
    └── bootstrap [--interactive] [USERNAME] [--instance INSTANCE] [--password-env PASSWORD-ENV] [--display-name DISPLAY-NAME] [--home HOME] [--json]  # Create the first owner in an explicitly empty managed-user instance.
```

## 路径检查

```bash
chatlogin paths my-site --json
chatlogin paths my-site --home "$HOME/.chatarch" --json
```

返回 `directory` 与 `database` 字段。显式 `--home` 优先于 ChatEnv 的默认 home；路径支持用户目录和已定义环境变量，拒绝未知变量与不安全实例名。此命令不创建目录、数据库或账户。

## 产品演示

```bash
python -m pip install "ChatLogin[demo]"
chatlogin serve
chatlogin serve --host 127.0.0.1 --port 8765 \
  --origin https://login.example.com
chatlogin serve --managed-demo
```

默认绑定 `127.0.0.1:8765`。非 loopback bind 若未提供 `--origin` 会失败；反向代理场景的 `--origin` 必须是浏览器访问的固定可信源，命令不会从 forwarded headers 推断它。演示只使用公开合成身份、短期有界 session 与一次性内存 fixture，详见[演示指南](demo.md)。

```text
Usage: chatlogin serve [OPTIONS]

Options:
  --host TEXT           Bind address; loopback by default.  [default: 127.0.0.1]
  --port INTEGER RANGE  TCP port.  [default: 8765; 1<=x<=65535]
  --origin TEXT         Fixed trusted public origin for browser Host/Origin checks.
  --managed-demo        Serve the disposable managed-users demonstration.
  --help                Show this message and exit.
```

`--managed-demo` 是显式选择的三账号内存演示；默认 `serve` 继续运行旧四后端演示。它需要 `ManagedUsers` 与 Web 预设，并不会读取生产/home 用户库。

## 托管用户首次 bootstrap

```bash
# APP_BOOTSTRAP_CREDENTIAL 是受控环境中的变量名，不是命令行密码值。
chatlogin users bootstrap operator \
  --instance my-site \
  --password-env APP_BOOTSTRAP_CREDENTIAL \
  --display-name "Operator" \
  --json
```

该命令只有一个目的：在明确为空的实例中创建第一个 owner。普通参数可用 ChatStyle 的 `-i/--interactive` 提示或 `-I/--no-interactive` 快速失败；无论哪种方式都不会输入原始密码或自动确认创建。它在写入前尽可能验证路径、实例和环境变量；重复初始化或不安全状态失败时非零退出，且没有 `--force`、chmod 修复。成功输出只含安全用户记录。后续账户管理通过 Web/API 完成，见[托管用户](managed-users.md)。

## 验证命令

```bash
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
```

本页的完整树来自 `chatlogin --tree` 实际读回，简明树来自 `chatlogin --tree-brief`；新增命令时同步更新测试和本页。网页接入见 [接入与安全](integration.md)。
