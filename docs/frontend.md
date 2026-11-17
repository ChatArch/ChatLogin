# TypeScript 与 React 前端接入

`@chatarch/chatlogin` 让自有 JavaScript/TypeScript 前端复用 ChatLogin 的 HTTP 契约和视觉资源。Python 包继续负责密码校验、账号、会话及服务端权限检查；npm 包不增加认证后端。它兼容 Python provider 0.2.1 起的发现 schema 1，npm 与 Python 分别维护版本。

当前源码包为 0.1.0；registry 发布是独立流程，此源码变更不自动发布。正式发布前可先用包内 `npm run build`、`npm pack` 生成本地 tarball 进行接入验证。

## 无框架客户端

发布前可按[包 README](https://github.com/ChatArch/ChatLogin/tree/main/packages/chatlogin)生成并安装本地 `.tgz`；正式发布后使用下面的安装命令。在浏览器入口创建客户端：

```bash
npm install @chatarch/chatlogin
```

```typescript
import { createChatLoginClient } from '@chatarch/chatlogin';

const client = createChatLoginClient({ basePath: '/auth' });
const manifest = await client.discover();
const session = await client.session();

// 业务接口继续由服务端验证身份、CSRF 和资源归属。
const response = await client.request('/api/preferences', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ theme: 'dark' }),
});
if (!response.ok) {
  // 宿主处理权限、会话变化和业务错误；不要自动重放写请求。
}
```

| 方法 | 行为 |
| --- | --- |
| `discover(options?)` | 读取 `{basePath}/api`，验证 schema、同源路径和能力声明。 |
| `session(options?)` | 查询真实会话，返回身份及本次 CSRF token；不在客户端对象中缓存。 |
| `login({ username, password, next? }, options?)` | 先查会话，必要时附当前 CSRF，再发送登录请求；调用方从输入框临时提供口令。 |
| `logout(options?)` | 查询会话并用 CSRF 请求撤销；确认未登录或撤销成功后才返回成功。 |
| `request(path, init?)` | 发送同源业务请求；写方法先查询新会话并附 CSRF，返回原生 `Response`。 |

认证方法区分 HTTP、协议与网络错误；`ChatLoginHTTPError.status` 可用于呈现 401、403 或 429。业务 `request()` 的响应状态由宿主检查；不会自动重试写入。方法支持取消信号，客户端也设置有界超时。

同一客户端实例的登录与退出按顺序执行，相邻退出可以合并，避免“退出成功后在途登录又建立会话”。跨标签页或其他客户端实例仍可能改变 Cookie；宿主应重新查询会话并更新界面，不能把本地状态当成持续有效的授权。

## 可选 React 组件

基础入口不导入 React。React 使用者另行安装兼容版本，并通过独立子路径导入组件：

```tsx
import { createChatLoginClient } from '@chatarch/chatlogin';
import { LoginForm, AccountMenu } from '@chatarch/chatlogin/react';
import '@chatarch/chatlogin/styles/login.css';
import '@chatarch/chatlogin/styles/account-menu.css';

// 本示例在浏览器入口运行。
const client = createChatLoginClient({ basePath: '/auth' });

export function SignIn() {
  return <LoginForm client={client} title="项目登录" next="/" />;
}

export function Navigation() {
  return <AccountMenu client={client} mode="gear"
    onLogout={() => window.location.assign('/auth/')} />;
}
```

`LoginForm` 支持标题、中英文文案、调色板、布局与明暗外观。密码保留在非受控输入及本次请求内存中，提交后清空，不进入 React 状态；成功回调只收到用户与安全的本地 `next`。`AccountMenu` 提供加载、错误重试、身份、角色感知导航与真实退出。宿主主动登录或更改账号后，可改变 `refreshKey` 触发菜单重新查询。

固定账号后端会声明 `managed_users=false`、`profile=false`；菜单只呈现已声明且适合当前身份的能力。托管用户的资料与用户管理链接还取决于服务端返回的角色和页面。Headless 服务没有声明页面时，不会凭空生成页面入口。隐藏菜单不替代服务端权限与业务资源归属检查。

## 同源与安全约束

请求固定使用同源 Cookie、禁止重定向并禁用缓存。浏览器当前 origin 是信任边界，配置不能改成另一个站点；发现响应、页面链接和业务目标在发送 Cookie/CSRF 前验证。`origin` 与可注入 `fetch` 主要用于非浏览器测试，不是跨站登录配置。

前端不持久化密码、会话 token 或 CSRF；不把 Cookie 复制到 localStorage、sessionStorage 或 URL。`session()` 和底层登录结果中的 CSRF 是短暂请求材料，宿主也不应记录或持久化它。`publicSession()` 可去除 CSRF 后再交给展示层。

Python 服务继续强制 Host、Origin、CSRF、Cookie 属性及账号权限。`safeNext()` 只允许保守的本地跳转，Python 服务仍是最终校验方。账号过期、其他页面退出或 CSRF 变化后，重新查询会话并由宿主决定恢复流程；不得自动重放结果未知的业务写入。

## 协议和视觉资源共同维护

TypeScript 源码位于 `packages/chatlogin/src/`。构建将 `client.ts` 与共享 `ui.ts` 生成到 Python 的 `web/assets/client.js`、`ui.js`；默认 Python 登录页直接使用这些模块。React 组件和默认页因此共享 HTTP 客户端及文案规则，不各自维护一套登录请求实现。

CSS 以 Python `src/chatlogin/web/assets/` 为单源，构建复制到 npm 的 `styles/`。保持相同的类名、主题变量与视觉选项；CSS 仅作用于组件或显式选择加入的独立页面，不重置嵌入应用的 body。

修改协议或样式时，同步契约测试、文档和生成产物。使用包内 `npm run build` 生成、`npm run check:shared` 检查漂移，再运行客户端、React 与真实 Python ASGI 契约检查。Python 安装包携带已生成模块，服务启动无需 Node.js；npm 分发携带编译后的 ESM、类型和 CSS，基础消费者无需 React。

## Headlamp 为什么继续采用认证代理

Headlamp 支持 HTTP 认证代理。Python ChatLogin 可以提供同源登录页与会话校验，由受控代理向 Go Headlamp 传入已验证身份；两端不需要使用相同语言。后端监听、身份头覆盖和 Kubernetes ServiceAccount 权限仍由部署方管理。

npm 包解决自有前端的复用问题，不会替第三方应用验证服务端请求，也不自动建立集中式身份服务、跨站共享 Cookie 或 SSO。无需为了安装 npm 包而修改 Headlamp 前端或重写 Node.js 认证服务。

继续阅读：[新服务接入](service-onboarding.md)、[接入与安全边界](integration.md)、[托管用户](managed-users.md)。
