# CLI 树

可复用认证与网页能力由 [Python 接口](interface-tree.md) 提供。命令行还可运行隔离产品演示；它不是生产登录微服务。

## 顶层命令

```text
chatlogin
├── --help                                      # 查看帮助
├── --version                                   # 查询安装版本
├── --tree                                      # 真实命令树，含参数
├── --tree-brief                                # 简明命令树
├── paths <INSTANCE> [--home HOME] [--json]      # 只读解析实例运行路径
└── serve [--host HOST] [--port PORT] [--origin ORIGIN]
                                                    # 运行隔离合成演示
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
```

默认绑定 `127.0.0.1:8765`。非 loopback bind 若未提供 `--origin` 会失败；反向代理场景的 `--origin` 必须是浏览器访问的固定可信源，命令不会从 forwarded headers 推断它。演示只使用公开合成身份、短期有界 session 与一次性内存 fixture，详见[演示指南](demo.md)。

```text
Usage: chatlogin serve [OPTIONS]

Options:
  --host TEXT           Bind address; loopback by default.  [default: 127.0.0.1]
  --port INTEGER RANGE  TCP port.  [default: 8765; 1<=x<=65535]
  --origin TEXT         Fixed trusted public origin for browser Host/Origin checks.
  --help                Show this message and exit.
```

## 验证命令

```bash
chatlogin --version
chatlogin --tree
chatlogin --tree-brief
```

命令树直接来自 ChatStyle 和 Click 已注册元数据；新增命令时同步更新测试和本页。网页接入见 [接入与安全](integration.md)。
