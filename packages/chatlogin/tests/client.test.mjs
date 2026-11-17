import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { ChatLoginClient, ChatLoginHTTPError, ChatLoginNetworkError, ChatLoginProtocolError,
  accountLinks, publicSession, safeNext, uiTokens } from '../dist/index.js';

const fixture = JSON.parse(await readFile(new URL('./fixtures/http-contract.json', import.meta.url)));
const { fixed, managed } = fixture;
const origin = 'https://accounts.example.test', basePath = '/portal/auth';
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

function scripted(steps, options = {}) {
  const calls = [];
  const client = new ChatLoginClient({ origin, basePath, ...options, fetch: async (url, init) => {
    calls.push({ url, init });
    const step = steps.shift();
    assert.ok(step, 'Unexpected request');
    assert.equal(url, origin + step.path);
    assert.equal(init.method ?? 'GET', step.method ?? 'GET');
    assert.equal(init.credentials, 'same-origin'); assert.equal(init.mode, 'same-origin');
    assert.equal(init.cache, 'no-store'); assert.equal(init.redirect, 'error');
    assert.equal(init.headers.has('Cookie'), false); assert.equal(init.headers.has('Authorization'), false);
    assert.equal(init.headers.has('Origin'), false); assert.equal(init.headers.has('X-ChatLogin-Client'), false);
    step.inspect?.(init);
    return step.response ?? json(step.data, step.status);
  } });
  return { client, calls, done: () => assert.equal(steps.length, 0) };
}

test('real fixed and managed discovery/session contracts, mount prefix and UI parity', async () => {
  for (const manifest of [fixed.discovery, managed.discovery, managed.headless_discovery]) {
    const run = scripted([{ path: basePath + '/api', data: manifest }, { path: basePath + '/session', data: fixed.anonymous }]);
    assert.deepEqual(await run.client.discover(), manifest);
    assert.deepEqual(await run.client.session(), fixed.anonymous);
    run.done();
  }
  for (const key of ['palettes', 'layouts', 'appearances']) assert.deepEqual([...uiTokens[key]].sort(), fixture.ui[key]);
});

test('fixed accounts, managed roles, and headless advertise only available navigation', () => {
  assert.deepEqual(accountLinks(fixed.discovery, publicSession(fixed.session)), []);
  assert.deepEqual(accountLinks(fixed.discovery, publicSession(fixed.anonymous)), [{ key: 'login', url: basePath + '/' }]);
  assert.deepEqual(accountLinks(managed.discovery, publicSession(managed.roles.member)).map(link => link.key), ['profile']);
  assert.deepEqual(accountLinks(managed.discovery, publicSession(managed.roles.owner)).map(link => link.key), ['profile', 'users']);
  assert.deepEqual(accountLinks(managed.headless_discovery, publicSession(managed.roles.owner)), []);
  assert.deepEqual(Object.keys(publicSession(fixed.session)).sort(), ['authenticated', 'user']);
});

test('login gets fresh CSRF before rotating an existing session; logout gets a newer token', async () => {
  const newer = { ...fixed.session, csrf_token: 'newer-csrf' };
  const run = scripted([
    { path: basePath + '/session', data: fixed.session },
    { path: basePath + '/login', method: 'POST', data: fixed.login, inspect: init => {
      assert.equal(init.headers.get('X-CSRF-Token'), fixed.session.csrf_token);
      assert.deepEqual(JSON.parse(init.body), { username: 'fixture', password: 'fixture-password', next: '/workspace' });
    } },
    { path: basePath + '/session', data: newer },
    { path: basePath + '/logout', method: 'POST', data: fixed.logout, inspect: init => {
      assert.equal(init.headers.get('X-CSRF-Token'), 'newer-csrf'); assert.equal(init.body, undefined);
    } },
  ]);
  assert.deepEqual(await run.client.login({ username: 'fixture', password: 'fixture-password', next: '/workspace', role: 'owner' }), fixed.login);
  assert.deepEqual(await run.client.logout(), fixed.logout);
  assert.equal('csrf_token' in run.client, false); assert.equal('password' in run.client, false);
  run.done();
});

test('anonymous login and idempotent anonymous logout do not invent CSRF/native credentials', async () => {
  const run = scripted([
    { path: basePath + '/session', data: fixed.anonymous },
    { path: basePath + '/login', method: 'POST', data: { ...fixed.login, next: '//evil.example/' }, inspect: init => {
      assert.equal(init.headers.has('X-CSRF-Token'), false); assert.equal(JSON.parse(init.body).next, '/');
    } },
    { path: basePath + '/session', data: fixed.anonymous },
  ]);
  assert.equal((await run.client.login({ username: 'fixture', password: 'fixture-password', next: 'https://evil.example' })).next, '/');
  assert.deepEqual(await run.client.logout(), { authenticated: false }); run.done();
});

test('concurrent logout is coalesced and a failed operation can be retried', async () => {
  const gate = deferred(); let sessions = 0, writes = 0;
  const client = new ChatLoginClient({ origin, fetch: async (url, init) => {
    if (url.endsWith('/session')) { sessions++; await gate.promise; return json(fixed.session); }
    writes++; return json(writes === 1 ? { detail: 'forbidden' } : fixed.logout, writes === 1 ? 403 : 200);
  } });
  const first = client.logout(), second = client.logout();
  assert.strictEqual(first, second); gate.resolve();
  await assert.rejects(first, error => error instanceof ChatLoginHTTPError && error.status === 403);
  assert.equal(sessions, 1); assert.equal(writes, 1);
  assert.deepEqual(await client.logout(), { authenticated: false }); assert.equal(writes, 2);
});

test('login in flight is completed before logout reads and revokes the resulting cookie', async () => {
  let authenticated = false, loginStarted = deferred(), releaseLogin = deferred(), logoutWrites = 0;
  const order = [];
  const client = new ChatLoginClient({ origin, fetch: async (url, init) => {
    if (url.endsWith('/session')) { order.push('session:' + authenticated); return json(authenticated ? fixed.session : fixed.anonymous); }
    if (url.endsWith('/login')) {
      order.push('login'); loginStarted.resolve(); await releaseLogin.promise; authenticated = true; return json(fixed.login);
    }
    assert.equal(init.headers.get('X-CSRF-Token'), fixed.session.csrf_token);
    order.push('logout'); logoutWrites++; authenticated = false; return json(fixed.logout);
  } });
  const login = client.login({ username: 'fixture', password: 'fixture-password' }); await loginStarted.promise;
  const logout = client.logout(); releaseLogin.resolve(); await Promise.all([login, logout]);
  assert.equal(authenticated, false); assert.equal(logoutWrites, 1);
  assert.deepEqual(order, ['session:false', 'login', 'session:true', 'logout']);
});

test('logout -> login -> logout does not merge across an intervening login', async () => {
  let authenticated = true, logoutWrites = 0;
  const client = new ChatLoginClient({ origin, fetch: async url => {
    if (url.endsWith('/session')) return json(authenticated ? fixed.session : fixed.anonymous);
    if (url.endsWith('/login')) { authenticated = true; return json(fixed.login); }
    logoutWrites++; authenticated = false; return json(fixed.logout);
  } });
  const before = client.logout(), login = client.login({ username: 'fixture', password: 'fixture-password' }), after = client.logout();
  assert.notStrictEqual(before, after); await Promise.all([before, login, after]);
  assert.equal(authenticated, false); assert.equal(logoutWrites, 2);
});

test('same-origin application writes overwrite caller CSRF and never auto-retry 403', async () => {
  const run = scripted([
    { path: basePath + '/session', data: fixed.session },
    { path: '/private/write', method: 'PATCH', status: 403, data: { detail: 'expired' }, inspect: init =>
      assert.equal(init.headers.get('X-CSRF-Token'), fixed.session.csrf_token) },
    { path: basePath + '/session', data: { ...fixed.session, csrf_token: 'rotated-csrf' } },
    { path: '/private/write', method: 'PATCH', data: { ok: true }, inspect: init =>
      assert.equal(init.headers.get('X-CSRF-Token'), 'rotated-csrf') },
    { path: '/public/read', data: { ok: true } },
  ]);
  const denied = await run.client.request('/private/write', { method: 'PATCH', headers: { 'X-CSRF-Token': 'forged' } });
  assert.equal(denied.status, 403);
  await run.client.request('/private/write', { method: 'PATCH', credentials: 'include', mode: 'cors', redirect: 'follow', cache: 'force-cache' });
  await run.client.request('/public/read', { headers: { 'X-CSRF-Token': 'stale-read-token' } }); run.done();
});

test('anonymous unsafe requests fail before the business write', async () => {
  const run = scripted([{ path: basePath + '/session', data: fixed.anonymous }]);
  await assert.rejects(run.client.request('/write', { method: 'POST' }), error => error.status === 401);
  run.done();
});

test('cross-origin, ambiguous paths, and invalid discovered endpoints fail closed', async () => {
  let requests = 0;
  const client = new ChatLoginClient({ origin, fetch: async () => { requests++; return json(fixed.anonymous); } });
  for (const path of ['https://evil.example/', '//evil.example/', '/%2f%2fevil.example', '/\\evil.example', '/x%0a']) {
    assert.throws(() => client.request(path, { method: 'POST' }), TypeError);
  }
  assert.equal(requests, 0);
  for (const invalid of ['https://evil.example/auth', '//evil.example/auth', '/a/../auth', '/%61uth', '/auth?x=1']) {
    assert.throws(() => new ChatLoginClient({ origin, basePath: invalid }));
  }
  for (const mutate of [data => { data.pages.login = 'https://evil.example/'; }, data => { data.operations[0].path = '//evil.example/'; },
                         data => { data.schema_version = 2; }, data => { data.capabilities.profile = 'true'; }]) {
    const data = structuredClone(fixed.discovery); mutate(data);
    const run = scripted([{ path: basePath + '/api', data }]);
    await assert.rejects(run.client.discover(), ChatLoginProtocolError); run.done();
  }
});

test('browser origin cannot be changed through configuration', () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'location');
  Object.defineProperty(globalThis, 'location', { value: { origin }, configurable: true });
  try { assert.throws(() => new ChatLoginClient({ origin: 'https://evil.example' }), TypeError); }
  finally { if (previous) Object.defineProperty(globalThis, 'location', previous); else delete globalThis.location; }
});

test('credentials and HTTP bodies are never reflected in errors', async () => {
  const run = scripted([{ path: basePath + '/session', data: fixed.anonymous },
    { path: basePath + '/login', method: 'POST', status: 401, data: { detail: 'fixture-password secret-token' } }]);
  await assert.rejects(run.client.login({ username: 'fixture', password: 'fixture-password' }), error => {
    assert.equal(error.status, 401); assert.doesNotMatch(String(error), /fixture-password|secret-token/); return true;
  });
  const client = new ChatLoginClient({ origin, fetch: async () => { throw Error('fixture-password'); } });
  await assert.rejects(client.session(), error => error instanceof ChatLoginNetworkError && !String(error).includes('fixture-password'));
  run.done();
});

test('malformed/HTML/oversized JSON, invalid principals and empty CSRF are rejected', async () => {
  const badResponses = [new Response('<html>Sign in</html>', { headers: { 'Content-Type': 'text/html' } }),
    new Response('{bad', { headers: { 'Content-Type': 'application/json' } }),
    json({ x: 'a'.repeat(66000) }), json({ ...fixed.session, csrf_token: '' }),
    json({ ...fixed.session, user: { ...fixed.session.user, role: 'guest' } }), json({ authenticated: false })];
  for (const response of badResponses) {
    const run = scripted([{ path: basePath + '/session', response }]);
    await assert.rejects(run.client.session(), ChatLoginProtocolError); run.done();
  }
});

test('timeouts and caller cancellation are bounded and do not retry', async () => {
  let calls = 0;
  const client = new ChatLoginClient({ origin, timeoutMs: 15, fetch: (_url, init) => new Promise((_resolve, reject) => {
    calls++; init.signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true });
  }) });
  await assert.rejects(client.session(), ChatLoginNetworkError); assert.equal(calls, 1);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(client.session({ signal: controller.signal }), ChatLoginNetworkError); assert.equal(calls, 1);
});

test('safe-next behavior follows actual Python vectors including nested/invalid encodings', () => {
  for (const vector of fixture.safe_next) assert.equal(safeNext(vector.input), vector.expected, JSON.stringify(vector.input));
});
