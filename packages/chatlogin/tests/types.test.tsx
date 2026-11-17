import { createChatLoginClient, accountLinks, publicSession } from '../dist/index.js';
import type { Discovery, Session } from '../dist/index.js';
import { AccountMenu, LoginForm } from '../dist/react.js';

const client = createChatLoginClient({ basePath: '/auth' });
client.request('/private', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
// @ts-expect-error browser Cookie policy cannot be overridden
client.request('/private', { credentials: 'include' });
// @ts-expect-error unknown roles must not be injected into login
client.login({ username: 'fixture', password: 'fixture-password', role: 'owner' });
const session: Session = await client.session();
const manifest: Discovery = await client.discover();
accountLinks(manifest, publicSession(session));
if (session.authenticated) session.user.user_id.toUpperCase();
const form = <LoginForm client={client} layout="split" onSuccess={result => {
  result.user.display_name.toUpperCase();
  // @ts-expect-error UI callbacks do not expose credentials/CSRF
  result.csrf_token;
}} />;
const menu = <AccountMenu client={client} refreshKey={1} mode="gear" />;
void form; void menu;
