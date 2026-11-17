# @chatarch/chatlogin

ChatLogin 的同源浏览器客户端，以及可选 React 登录和账号菜单。Python provider 继续校验密码、管理账号和会话、检查 CSRF 与权限；此包不提供认证后端或跨站 SSO。

源码包版本 `0.1.0`，使用 Python ChatLogin `0.2.1` 引入的 HTTP schema v1。npm 与 Python 独立版本；此源码变更不自动发布 registry，首次发布前可按下面的打包流程安装本地 `.tgz`。

## 基础客户端

发布后安装 `npm install @chatarch/chatlogin`。基础入口没有运行时依赖，不需要 React；仅提供 ESM，支持现代浏览器的 Fetch、Cookie、AbortController 和 TextDecoder。

```ts
import { createChatLoginClient, ChatLoginHTTPError } from '@chatarch/chatlogin';

const auth = createChatLoginClient({ basePath: '/auth' });
const manifest = await auth.discover(); // /auth/api; schema, real pages and capabilities
const session = await auth.session();  // public identity + short-lived in-memory CSRF

await auth.login({ username, password, next: '/workspace' });
// Browser owns the HttpOnly session cookie. Do not save passwords or CSRF.
const response = await auth.request('/api/preferences', {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ theme: 'dark' }),
});
await auth.logout();
```

`basePath` 是浏览器可见的安全绝对路径，包含 ASGI mount 前缀，例如 `/tools/admin`。不能填外部 URL。客户端总是使用 `credentials: 'same-origin'`、`mode: 'same-origin'`、`cache: 'no-store'`、`redirect: 'error'`，不手设 Origin、Cookie 或 Authorization。构造函数的 `origin`/`fetch` 是无浏览器契约测试的注入点；浏览器内 `origin` 必须与当前页面一致。

登录前读新鲜会话，已有 Cookie 时带新鲜 CSRF；退出和业务写请求也重新查询。`request()` 为 POST/PUT/PATCH/DELETE 加 CSRF，拒绝匿名写入，GET/HEAD/OPTIONS 不携带 CSRF。它返回原始业务 Response（含非 2xx），由宿主检查 `response.ok` 并解释业务错误。认证方法及会话预检查的非 2xx 抛 `ChatLoginHTTPError`，不会把服务端正文或凭据放进错误信息。403、网络失败和超时不自动重试有副作用的请求。默认每次操作 15 秒，可配置 `timeoutMs`（0–120000 之间的正数），或传入 `signal`。

同一客户端实例的登录与退出完整串行，只有相邻的并发退出合并；合并时第一个调用者拥有取消信号。其他客户端实例、浏览器标签页及服务端密码/角色变化仍需宿主重新读取会话。客户端不缓存认证状态、不操作 localStorage/sessionStorage，也不读取会话 Cookie。

## 可选 React

只有导入 `@chatarch/chatlogin/react` 才需要宿主提供 React `^18.2.0 || ^19.0.0`。样式显式引入；不会自动修改宿主 body。

```tsx
import { useState } from 'react';
import { createChatLoginClient } from '@chatarch/chatlogin';
import { LoginForm, AccountMenu } from '@chatarch/chatlogin/react';
import '@chatarch/chatlogin/styles/login.css';
import '@chatarch/chatlogin/styles/account-menu.css';

const auth = createChatLoginClient({ basePath: '/auth' }); // in the browser

export function AccountArea() {
  const [revision, refresh] = useState(0);
  return <>
    <AccountMenu client={auth} refreshKey={revision} onLogout={() => refresh(n => n + 1)} />
    <LoginForm client={auth} layout="split" appearance="system"
      onSuccess={() => refresh(n => n + 1)} />
  </>;
}
```

`LoginForm` 支持 title/subtitle/eyebrow、三种 palette、card/split、light/dark/system、zh-CN/en，以及可信宿主的本地 guestUrl。无 `onSuccess` 时跳转到经验证的同源 `next`；提供回调则由宿主处理导航。密码不进入 React state，回调只返回 user/next，不含密码或 CSRF。

`AccountMenu` 支持 gear/links、zh-CN/en、refreshKey、onLogout/onError。状态存储只含公开身份，不保留 CSRF。固定账号显示身份与真实退出，不捏造用户管理链接；托管用户仅在能力、真实页面和角色匹配时显示资料/管理链接；headless 的 `pages={}` 不产生链接。菜单提示不是权限检查，服务端仍须检查业务数据归属。跨标签页变化由宿主触发 refreshKey；不做跨站身份同步。

## 共享维护与验证

单源方向如下，`npm run check:shared` 会在漂移时失败：

1. `src/client.ts`、`src/ui.ts` → 编译为 npm ESM 与 Python 默认页的 `client.js`、`ui.js`。
2. Python `src/chatlogin/web/assets/{login,account-menu}.css` → npm `styles/`；两端共用 `--cl-*`、class、主题和布局约定。
3. `scripts/http_contract.py` 从真实 Python ASGI 路由生成脱敏 fixtures；`--check` 验证协议与 UI tokens，Node 测试消费这些 fixtures。

Python 的已构建 wheel 包含生成的浏览器资源，生产安装不需要 Node。Jinja 与 React 保留各自的语义标记；公共 class、默认字段/主题及协议由契约测试约束。不要手工修改生成的 client/ui JavaScript 或 npm CSS 副本。

```sh
cd packages/chatlogin
npm ci --ignore-scripts
npm run build
python scripts/http_contract.py --check # use a Python env with ChatLogin[web]
npm run check:shared
npm test
npm run typecheck
npm run pack:check
```

`pack:check` 检查 tarball 白名单，在无 React 的干净消费者中安装并导入基础包、编译其公开类型。它不调用 publish。更多说明见仓库 [frontend.md](https://github.com/ChatArch/ChatLogin/blob/main/docs/frontend.md)，接入示例见 [examples/](https://github.com/ChatArch/ChatLogin/tree/main/examples/frontend)。Headlamp 等 Go 服务仍通过 HTTP 认证代理保护；npm 包用于自有 JS/TS 界面复用，无法替代服务器密码与权限校验。
