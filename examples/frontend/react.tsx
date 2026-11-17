/** Browser client component. Instantiate after hydration in SSR hosts. */
import { useMemo, useState } from 'react';
import { createChatLoginClient } from '@chatarch/chatlogin';
import { AccountMenu, LoginForm } from '@chatarch/chatlogin/react';
import '@chatarch/chatlogin/styles/login.css';
import '@chatarch/chatlogin/styles/account-menu.css';

export function AccountArea() {
  const auth = useMemo(() => createChatLoginClient({ basePath: '/auth' }), []);
  const [revision, refresh] = useState(0);
  return <>
    <AccountMenu client={auth} refreshKey={revision} onLogout={() => refresh(value => value + 1)} />
    <LoginForm client={auth} title="My application" layout="split" appearance="system"
      onSuccess={() => refresh(value => value + 1)} />
  </>;
}
