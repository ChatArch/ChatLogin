/** Exercise the actual tarball and public types without installing React. */
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, mkdtemp, stat, rename } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scratchRoot = process.env.CHATLOGIN_TEST_ROOT ?? process.env.RUNNER_TEMP ?? path.join(root, 'node_modules/.cache/chatlogin-tests');
await mkdir(scratchRoot, { recursive: true });
const scratch = await mkdtemp(path.join(scratchRoot, 'chatlogin-pack-'));
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error('Run via npm run pack:check');
function run(command, args, cwd = root) {
  const result = spawnSync(command, args, { cwd, encoding: 'utf8', timeout: 120000,
    env: { ...process.env, PATH: path.dirname(process.execPath) + path.delimiter + process.env.PATH } });
  if (result.status !== 0) throw new Error('Distribution check failed: ' + result.stderr.slice(-2000));
  return result.stdout;
}
try {
  const metadata = JSON.parse(run(process.execPath, [npmCli, 'pack', '--json', '--ignore-scripts', '--pack-destination', scratch]))[0];
  const paths = metadata.files.map(file => file.path);
  assert.ok(paths.includes('dist/index.js') && paths.includes('dist/react.js') && paths.includes('styles/login.css'));
  assert.ok(paths.every(value => /^(package\.json|LICENSE|README\.md|dist\/[a-z-]+\.(js|d\.ts)|styles\/(login|account-menu)\.css)$/.test(value)), 'Unexpected tarball content');
  const tarball = path.join(scratch, metadata.filename), consumer = path.join(scratch, 'consumer');
  await mkdir(consumer);
  await writeFile(path.join(consumer, 'package.json'), JSON.stringify({ private: true, type: 'module' }));
  run(process.execPath, [npmCli, 'install', '--offline', '--ignore-scripts', '--omit=peer', '--no-audit', '--no-fund', '--package-lock=false', tarball], consumer);
  const hasReact = await stat(path.join(consumer, 'node_modules/react')).then(() => true, () => false);
  assert.equal(hasReact, false, 'The base consumer should not install React');
  run(process.execPath, ['--input-type=module', '-e', `
    import { createChatLoginClient, safeNext } from '@chatarch/chatlogin';
    const auth = createChatLoginClient({origin:'https://accounts.example.test'});
    if(auth.basePath!=='/auth'||safeNext('//evil.example')!=='/')throw Error('Invalid public entry');
  `], consumer);
  await writeFile(path.join(consumer, 'index.ts'), `
    import {createChatLoginClient} from '@chatarch/chatlogin';
    const auth=createChatLoginClient({origin:'https://accounts.example.test'});
    const state=await auth.session();if(state.authenticated)state.user.user_id.toUpperCase();
  `);
  await writeFile(path.join(consumer, 'tsconfig.json'), JSON.stringify({ compilerOptions: {
    target: 'ES2020', module: 'NodeNext', moduleResolution: 'NodeNext', strict: true, noEmit: true, types: [], lib: ['ES2020', 'DOM'] }, include: ['index.ts'] }));
  run(process.execPath, [path.join(root, 'node_modules/typescript/bin/tsc'), '-p', consumer]);
  for (const name of ['login', 'account-menu']) {
    assert.deepEqual(await readFile(path.join(consumer, 'node_modules/@chatarch/chatlogin/styles', name + '.css')),
      await readFile(path.join(root, 'styles', name + '.css')));
  }
  console.log(JSON.stringify({ name: metadata.name, version: metadata.version, files: paths.length, bytes: metadata.size,
    cleanConsumer: true, reactInstalled: false, publicTypes: true, published: false }));
} finally {
  const trash = path.join(scratchRoot, '.trash'); await mkdir(trash, { recursive: true });
  await rename(scratch, path.join(trash, path.basename(scratch)));
}
