# TypeScript and React integration

`@chatarch/chatlogin` lets application-owned JavaScript/TypeScript frontends reuse ChatLogin's HTTP contract and visual resources. The Python package remains responsible for passwords, accounts, sessions, and server-side authorization. The npm package supports discovery schema 1 from Python provider 0.2.1 onward; npm and Python versions are maintained independently.

The current source package is 0.1.0. Registry publishing is a separate release step; this source change does not publish it automatically. Before release, use the package's `npm run build` and `npm pack` to verify a local tarball.

## Framework-neutral client

Before registry publication, follow the [package README](https://github.com/ChatArch/ChatLogin/tree/main/packages/chatlogin) to build and install a local `.tgz`. After publication, use the installation command below. Create the client in a browser entry point:

```bash
npm install @chatarch/chatlogin
```

```typescript
import { createChatLoginClient } from '@chatarch/chatlogin';

const client = createChatLoginClient({ basePath: '/auth' });
const manifest = await client.discover();
const session = await client.session();

const response = await client.request('/api/preferences', {
  method: 'PATCH',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ theme: 'dark' }),
});
if (!response.ok) {
  // Handle authorization, session changes, and business errors in the host.
  // Do not automatically replay writes.
}
```

| Method | Behavior |
| --- | --- |
| `discover(options?)` | Reads `{basePath}/api` and validates the schema, same-origin paths, and declared capabilities. |
| `session(options?)` | Reads the real session, including its current CSRF token, without caching it on the client object. |
| `login({ username, password, next? }, options?)` | Queries the session first and supplies CSRF when needed; the host supplies the password temporarily from its input. |
| `logout(options?)` | Queries the session and requests CSRF-protected revocation; succeeds only after confirming an anonymous session or successful revocation. |
| `request(path, init?)` | Sends a same-origin business request; unsafe methods obtain fresh session CSRF. Returns a native `Response`. |

Authentication methods distinguish HTTP, protocol, and network errors. `ChatLoginHTTPError.status` supports handling 401, 403, or 429. The host checks business `request()` response status; writes are never retried automatically. Operations accept cancellation signals and use a bounded timeout.

Login and logout mutations on one client instance run in order; adjacent logout calls may share work. This prevents an in-flight login from silently establishing a session after a completed logout. Other tabs and client instances can still change the Cookie. Hosts must refresh their session view rather than treating local state as durable authorization.

## Optional React components

The base entry point does not import React. Install a compatible React version separately and import components from the dedicated subpath:

```tsx
import { createChatLoginClient } from '@chatarch/chatlogin';
import { LoginForm, AccountMenu } from '@chatarch/chatlogin/react';
import '@chatarch/chatlogin/styles/login.css';
import '@chatarch/chatlogin/styles/account-menu.css';

// This example runs in a browser entry point.
const client = createChatLoginClient({ basePath: '/auth' });

export function SignIn() {
  return <LoginForm client={client} title="Project sign-in" language="en" next="/" />;
}

export function Navigation() {
  return <AccountMenu client={client} language="en" mode="gear"
    onLogout={() => window.location.assign('/auth/')} />;
}
```

`LoginForm` supports branding, Chinese/English copy, palettes, layouts, and appearance settings. Passwords stay in uncontrolled inputs and request memory, are cleared on submission, and never enter React state. Its success callback receives only the principal and safe local `next`. `AccountMenu` provides loading, retry, identity, role-aware links, and real logout. Change `refreshKey` after host-initiated login or account changes to refresh it.

Fixed-account backends declare `managed_users=false` and `profile=false`. Menus show only declared capabilities appropriate for the current principal. Managed-user profile and administration links also depend on returned roles and pages. Headless providers do not invent missing page links. Navigation visibility never replaces server-side authorization or business-resource ownership checks.

## Same-origin security

Requests use same-origin Cookies, reject redirects, and disable caching. The current browser origin is authoritative; configuration cannot switch to another site. Discovery paths, page links, and business targets are validated before sending Cookie or CSRF material. Explicit `origin` and injectable `fetch` mainly support non-browser tests, not cross-site login.

Do not persist passwords, session tokens, or CSRF in localStorage, sessionStorage, URLs, or logs. CSRF returned by `session()` and low-level login results is temporary request material. Use `publicSession()` to remove it before passing session information to a display layer.

The Python service continues enforcing Host, Origin, CSRF, Cookie settings, and account permissions. `safeNext()` permits conservative local navigation; the server remains the final validator. After expiration, logout elsewhere, or changed CSRF, query the session again and let the host choose recovery. Never automatically replay a write whose outcome is unknown.

## Shared contract and visual maintenance

TypeScript sources live under `packages/chatlogin/src/`. The build generates Python's `web/assets/client.js` and `ui.js` from `client.ts` and shared `ui.ts`. The default Python login page imports these modules, so React and the default page share the client and copy rules rather than maintaining separate login implementations.

Python's `src/chatlogin/web/assets/` owns CSS. The build copies it into npm `styles/`; keep class names, theme variables, and visual options aligned. Selectors target components or an explicitly opted-in standalone page, without resetting an embedding application's body.

When changing contracts or styles, update tests, documentation, and generated files together. Run package-local `npm run build`, `npm run check:shared`, client/React tests, and real Python ASGI contract checks. Python distributions include generated modules and need no Node.js at service startup. npm distributions contain compiled ESM, declarations, and CSS; base consumers do not need React.

## Why Headlamp still uses an authentication proxy

Headlamp supports HTTP authentication proxies. Python ChatLogin can supply same-origin login and session checks while a controlled proxy passes verified identity to Go Headlamp. Authentication and application components do not need the same implementation language. The deployment still owns backend binding, identity-header replacement, and Kubernetes ServiceAccount permissions.

The npm package serves application-owned frontends. It does not authorize third-party server requests or establish a centralized identity service, cross-site Cookies, or SSO. Integrating it does not require a Headlamp frontend fork or a Node.js authentication backend.

See [service onboarding](service-onboarding.en.md), [integration and security](integration.en.md), and [managed users](managed-users.en.md).
