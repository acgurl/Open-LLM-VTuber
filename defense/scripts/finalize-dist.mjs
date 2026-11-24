import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distHtmlPath = path.join(rootDir, 'dist', 'index.html');
const rootHtmlPath = path.join(rootDir, 'index.html');

if (!fs.existsSync(distHtmlPath)) {
  throw new Error(`Expected singlefile output at ${distHtmlPath}`);
}

const raw = fs.readFileSync(distHtmlPath, 'utf8').replace(/[ \t]+$/gm, '');
const normalized = `${raw.trimEnd()}\n`;
fs.writeFileSync(distHtmlPath, normalized, 'utf8');
fs.writeFileSync(rootHtmlPath, normalized, 'utf8');

const publicAssetsDir = path.join(rootDir, 'public', 'assets');
const rootAssetsDir = path.join(rootDir, 'assets');
fs.mkdirSync(rootAssetsDir, { recursive: true });
for (const file of fs.readdirSync(publicAssetsDir)) {
  fs.copyFileSync(path.join(publicAssetsDir, file), path.join(rootAssetsDir, file));
}
