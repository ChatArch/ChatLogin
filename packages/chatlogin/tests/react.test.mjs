import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { create, act } from 'react-test-renderer';
import { LoginForm, AccountMenu } from '../dist/react.js';
import { ChatLoginHTTPError } from '../dist/index.js';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const fixture = JSON.parse(await readFile(new URL('./fixtures/http-contract.json', import.meta.url)));
const renderers = [];
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const client = overrides => ({ basePath: '/portal/auth', discover: async () => fixture.fixed.discovery,
  session: async () => fixture.fixed.session, login: async () => fixture.fixed.login, logout: async () => fixture.fixed.logout, ...overrides });
async function mount(component) { let rendered; await act(async () => { rendered = create(component); }); renderers.push(rendered); return rendered; }
afterEach(async () => { for (const renderer of renderers.splice(0)) await act(async () => renderer.unmount()); });
const allText = renderer => JSON.stringify(renderer.toJSON());
const links = renderer => renderer.root.findAllByType('a').map(link => link.props.href);

test('login markup shares Python default classes, labels, theme flags, and escaped text', () => {
  const html = renderToStaticMarkup(React.createElement(LoginForm, { client: client(), title: '<Unsafe>', layout: 'split', appearance: 'dark' }));
  for (const name of fixture.ui.default_classes) assert.ok(html.includes('class="' + name + '"'), name);
  assert.ok(html.includes('&lt;Unsafe&gt;')); assert.ok(html.includes('data-layout="split"'));
  assert.ok(html.includes('data-appearance="dark"')); assert.match(html, /autocomplete="current-password"/i);
  assert.ok(html.includes('账号')); assert.ok(html.includes('密码')); assert.ok(html.includes('aria-live="polite"'));
  assert.throws(() => renderToStaticMarkup(React.createElement(LoginForm, { client: client(), guestUrl: '//evil.example' })), TypeError);
});

test('login submits once, clears uncontrolled password, and callbacks exclude CSRF', async () => {
  const gate = deferred(); let calls = 0, received, succeeded;
  const rendered = await mount(React.createElement(LoginForm, { client: client({ login: async input => { calls++; received = input; return gate.promise; } }),
    next: '/workspace', onSuccess: value => { succeeded = value; } }));
  const fields = { username: { value: 'fixture' }, password: { value: 'fixture-password' } };
  const event = { preventDefault() {}, currentTarget: { elements: { namedItem: name => fields[name] } } };
  let first;
  await act(async () => { first = rendered.root.findByType('form').props.onSubmit(event); rendered.root.findByType('form').props.onSubmit(event); });
  assert.equal(calls, 1); assert.equal(fields.password.value, '');
  assert.equal(received.password, 'fixture-password'); assert.equal(rendered.root.findByType('button').props.disabled, true);
  await act(async () => { gate.resolve(fixture.fixed.login); await first; });
  assert.deepEqual(Object.keys(succeeded).sort(), ['next', 'user']);
  assert.equal(rendered.root.findByType('button').props.disabled, false);
});

test('login 403 is shown safely; a late result after unmount does not call the host', async () => {
  const broken = await mount(React.createElement(LoginForm, { client: client({ login: async () => { throw new ChatLoginHTTPError(403); } }) }));
  const event = { preventDefault() {}, currentTarget: { elements: { namedItem: () => ({ value: 'fixture' }) } } };
  await act(async () => { await broken.root.findByType('form').props.onSubmit(event); });
  assert.ok(allText(broken).includes('会话已变化')); assert.equal(broken.root.findByType('button').props.disabled, false);
  const gate = deferred(); let callbacks = 0, task;
  const rendered = await mount(React.createElement(LoginForm, { client: client({ login: () => gate.promise }), onSuccess: () => { callbacks++; } }));
  await act(async () => { task = rendered.root.findByType('form').props.onSubmit(event); });
  await act(async () => rendered.unmount()); renderers.splice(renderers.indexOf(rendered), 1);
  await act(async () => { gate.resolve(fixture.fixed.login); await task; });
  assert.equal(callbacks, 0);
});

test('fixed account menu exposes real logout and no invented management pages', async () => {
  const rendered = await mount(React.createElement(AccountMenu, { client: client() }));
  assert.deepEqual(links(rendered), []); assert.ok(allText(rendered).includes('退出登录'));
  assert.ok(allText(rendered).includes('Fixture User')); assert.ok(!allText(rendered).includes('fixture-csrf'));
  await act(async () => { await rendered.root.findByType('button').props.onClick(); });
  assert.deepEqual(links(rendered), ['/portal/auth/']); assert.ok(allText(rendered).includes('访客'));
});

test('managed menu honors user/admin/owner capabilities and headless page absence', async () => {
  for (const [session, expected] of [[fixture.managed.roles.member, ['/portal/auth/profile']],
    [fixture.managed.roles.owner, ['/portal/auth/profile', '/portal/auth/users']]]) {
    const rendered = await mount(React.createElement(AccountMenu, { client: client({ discover: async () => fixture.managed.discovery, session: async () => session }) }));
    assert.deepEqual(links(rendered), expected);
  }
  const headless = await mount(React.createElement(AccountMenu, { client: client({ discover: async () => fixture.managed.headless_discovery }) }));
  assert.deepEqual(links(headless), []);
});

test('failed logout keeps authenticated identity; concurrent clicks coalesce and retry works', async () => {
  let calls = 0; const gate = deferred();
  const rendered = await mount(React.createElement(AccountMenu, { client: client({ logout: async () => { calls++; return calls === 1 ? gate.promise : fixture.fixed.logout; } }) }));
  let first;
  await act(async () => { first = rendered.root.findByType('button').props.onClick(); rendered.root.findByType('button').props.onClick(); });
  assert.equal(calls, 1);
  await act(async () => { gate.reject(new ChatLoginHTTPError(403)); await first; });
  assert.ok(allText(rendered).includes('Fixture User')); assert.ok(allText(rendered).includes('会话已变化'));
  await act(async () => { await rendered.root.findByType('button').props.onClick(); });
  assert.equal(calls, 2); assert.ok(allText(rendered).includes('访客'));
});

test('a delayed old account read cannot replace a newer authenticated identity', async () => {
  const slow = deferred();
  const oldClient = client({ session: () => slow.promise, discover: async () => fixture.managed.discovery });
  const newClient = client({ session: async () => fixture.managed.roles.member, discover: async () => fixture.managed.discovery });
  const rendered = await mount(React.createElement(AccountMenu, { client: oldClient }));
  await act(async () => rendered.update(React.createElement(AccountMenu, { client: newClient })));
  assert.deepEqual(links(rendered), ['/portal/auth/profile']);
  await act(async () => { slow.resolve(fixture.managed.roles.owner); });
  assert.deepEqual(links(rendered), ['/portal/auth/profile']); assert.ok(allText(rendered).includes('Fixture Member'));
});

test('discovery errors fail closed and can be retried without showing stale identity', async () => {
  let attempts = 0;
  const rendered = await mount(React.createElement(AccountMenu, { client: client({ discover: async () => {
    if (++attempts === 1) throw new ChatLoginHTTPError(503); return fixture.fixed.discovery;
  } }) }));
  assert.deepEqual(links(rendered), []); assert.ok(!allText(rendered).includes('Fixture User'));
  await act(async () => rendered.root.findByType('button').props.onClick());
  assert.ok(allText(rendered).includes('Fixture User'));
});
