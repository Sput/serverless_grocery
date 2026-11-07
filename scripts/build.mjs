// Local build only. No uploads or AWS calls.
import { build } from 'esbuild';
import { mkdir, readFile, writeFile, copyFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
const root = resolve(import.meta.dirname, '..');
const dist = resolve(root, 'dist');
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
const result = await build({
  entryPoints: [resolve(root, 'frontend/app.js')], bundle: true, minify: true,
  format: 'esm', target: ['es2022'], outdir: resolve(dist, 'assets'),
  entryNames: 'app-[hash]', metafile: true, legalComments: 'eof',
});
const asset = Object.keys(result.metafile.outputs).find(file => file.endsWith('.js'));
const relative = 'assets/' + asset.split('/').at(-1);
const html = (await readFile(resolve(root, 'frontend/index.html'), 'utf8')).replace('__APP_ASSET__', `./${relative}`);
await writeFile(resolve(dist, 'index.html'), html);
await copyFile(resolve(root, 'frontend/styles.css'), resolve(dist, 'styles.css'));
let config = {};
if (process.env.APP_CONFIG_FILE) config = JSON.parse(await readFile(process.env.APP_CONFIG_FILE, 'utf8'));
await writeFile(resolve(dist, 'config.js'), `window.APP_CONFIG = ${JSON.stringify(config, null, 2)};\n`);
await writeFile(resolve(dist, 'release.json'), JSON.stringify({ asset: relative }, null, 2) + '\n');
console.log(`Built static frontend in dist/ (${relative}). No AWS calls performed.`);
