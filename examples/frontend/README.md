# Browser integrations

Both examples consume the same-origin Python routes. Mount `FastAPIAuth` for fixed/callback accounts, or `create_managed_auth` for managed users, under `/auth` as described in [new-service onboarding](../../docs/service-onboarding.en.md). Set the server's concrete public Origin and keep server-side role/resource checks. Never pass production credentials through this source tree.

Build/pack the npm package first; a consuming application can install the resulting `.tgz` until a registry release exists. `vanilla.ts` expects host-owned `#sign-in` (username/password inputs), `#sign-in-status`, and optional `#sign-out`. `react.tsx` is a client-only component and imports styles explicitly. SSR hosts must instantiate the client after hydration, not while rendering on the server.

Use one stable client instance per auth prefix. Increment `AccountMenu.refreshKey` after login/account changes or when the host observes expiry in another tab. Do not infer authorization from visible menu links. These snippets do not start servers, create accounts, store passwords/tokens, provide SSO, or install a Node authentication backend.
