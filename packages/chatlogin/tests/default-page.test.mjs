/** Exercise the real default controller in a bounded DOM-port test, no server. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const assets = path.resolve(packageRoot, '../../src/chatlogin/web/assets');
const fixture = JSON.parse(await readFile(new URL('./fixtures/http-contract.json', import.meta.url)));
let sequence = 0;

async function page({ dataset = {}, loginStatus = 200, next = '/workspace' } = {}, inspect) {
  const descriptors = Object.fromEntries(['document', 'window', 'location', 'fetch'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const calls = [], navigation = [], status = { textContent: '' }, buttons = [{ disabled: false }, { disabled: true }];
  let submit, ariaBusy = false;
  const form = { elements: { username: { value: 'fixture' }, password: { value: 'fixture-password' } },
    querySelectorAll: () => buttons, addEventListener: (_name, callback) => { submit = callback; },
    setAttribute: () => { ariaBusy = true; }, removeAttribute: () => { ariaBusy = false; } };
  const root = { dataset: { sessionUrl: '/auth/session', loginUrl: '/auth/login', next: '/', ...dataset },
    querySelector: selector => selector === 'form' ? form : status };
  const values = { document: { querySelector: () => root }, location: { origin: 'https://accounts.example.test' },
    window: { location: { assign: value => navigation.push(value) } }, fetch: async (url, init) => {
      calls.push({ url, init });
      assert.ok(url.startsWith('https://accounts.example.test/auth/'));
      assert.equal(init.credentials, 'same-origin'); assert.equal(init.redirect, 'error');
      const session = url.endsWith('/session');
      return new Response(JSON.stringify(session ? fixture.fixed.session : { ...fixture.fixed.login, next }), {
        status: session ? 200 : loginStatus, headers: { 'Content-Type': 'application/json' } });
    } };
  for (const [key, value] of Object.entries(values)) Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  try {
    // Resolve to byte-identical npm artifacts so this test also runs on Node 18.
    const source = (await readFile(path.join(assets, 'login.js'), 'utf8'))
      .replace("'./client.js'", JSON.stringify(pathToFileURL(path.join(packageRoot, 'dist/client.js')).href))
      .replace("'./ui.js'", JSON.stringify(pathToFileURL(path.join(packageRoot, 'dist/ui.js')).href));
    await import('data:text/javascript;base64,' + Buffer.from(source + '\n// case ' + sequence++).toString('base64'));
    await inspect({ calls, navigation, status, buttons, form, submit: () => submit({ preventDefault() {} }), isBusy: () => ariaBusy });
  } finally {
    for (const [key, descriptor] of Object.entries(descriptors)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  }
}

test('shared client/UI and CSS files are exact distribution copies', async () => {
  for (const name of ['client', 'ui']) assert.deepEqual(await readFile(path.join(assets, name + '.js')), await readFile(path.join(packageRoot, 'dist', name + '.js')));
  for (const name of ['login', 'account-menu']) assert.deepEqual(await readFile(path.join(assets, name + '.css')), await readFile(path.join(packageRoot, 'styles', name + '.css')));
});

test('Python default controller uses the common CSRF flow and suppresses duplicate submits', async () => {
  await page({}, async state => {
    await Promise.all([state.submit(), state.submit()]);
    assert.equal(state.calls.length, 2); assert.equal(state.calls[1].init.headers.get('X-CSRF-Token'), 'fixture-csrf');
    assert.deepEqual(state.navigation, ['/workspace']); assert.equal(state.form.elements.password.value, '');
    assert.equal(state.isBusy(), false); assert.deepEqual(state.buttons.map(button => button.disabled), [false, true]);
  });
});

test('Python default controller recovers from 401 without exposing a credential', async () => {
  await page({ loginStatus: 401 }, async state => {
    await state.submit(); assert.deepEqual(state.navigation, []);
    assert.match(state.status.textContent, /账号或密码/); assert.doesNotMatch(state.status.textContent, /fixture-password/);
    assert.equal(state.form.elements.password.value, ''); assert.equal(state.buttons[0].disabled, false);
  });
});

test('Python default controller validates configured endpoints before sending anything', async () => {
  for (const dataset of [{ sessionUrl: 'https://evil.example/auth/session' }, { sessionUrl: '//evil.example/auth/session' },
    { loginUrl: '//evil.example/auth/login' }]) {
    await page({ dataset }, async state => { await state.submit(); assert.equal(state.calls.length, 0); assert.deepEqual(state.navigation, []); });
  }
});

test('Python default controller never follows an unsafe response next', async () => {
  await page({ next: '//evil.example/' }, async state => { await state.submit(); assert.deepEqual(state.navigation, ['/']); });
});
