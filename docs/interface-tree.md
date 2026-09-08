# Python 接口树

## 当前接口

```text
chatlogin
├── __version__             # 读取已安装的包版本
├── cli.main                # Click 命令行入口
└── config.ChatLoginConfig  # ChatEnv 扩展入口，暂无业务字段
```

```python
from chatlogin import __version__
from chatlogin.config import ChatLoginConfig
```

`ChatLoginConfig` 使用统一的 `ChatLogin` 命名空间；当前不要求密钥、不写入用户数据，也不发起网络请求。

## 范围

当前版本是初始模板，不包含认证服务、会话存储、用户数据库或登录页面。后续业务应通过可导入的 Python API 提供，命令行只作为薄适配层。
