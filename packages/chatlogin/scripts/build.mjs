/** Build ESM/types and synchronize checked-in Python browser assets. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repo = path.resolve(root, '../..'), check = process.argv.includes('--check');
const compiled = spawnSync(process.execPath, [path.join(root, 'node_modules/typescript/bin/tsc'), '-p', root], { cwd: root, stdio: 'inherit' });
if (compiled.status !== 0) process.exit(compiled.status ?? 1);
const assets = path.join(repo, 'src/chatlogin/web/assets');
const targets = [
  [path.join(root, 'dist/client.js'), path.join(assets, 'client.js')],
  [path.join(root, 'dist/ui.js'), path.join(assets, 'ui.js')],
  [path.join(assets, 'login.css'), path.join(root, 'styles/login.css')],
  [path.join(assets, 'account-menu.css'), path.join(root, 'styles/account-menu.css')],
  [path.join(repo, 'LICENSE'), path.join(root, 'LICENSE')],
];
for (const [source, target] of targets) {
  const expected = await readFile(source);
  if (check) {
    let actual;
    try { actual = await readFile(target); } catch { actual = null; }
    if (!actual?.equals(expected)) throw new Error(`Shared resource differs: ${path.relative(repo, target)}. Run npm run build.`);
  } else {
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, expected);
  }
}
console.log(check ? 'Shared Python/npm client and CSS verified.' : 'Built client, optional React entry, types and shared resources.');
