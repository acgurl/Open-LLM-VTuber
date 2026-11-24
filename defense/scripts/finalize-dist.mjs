import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const distHtmlPath = path.join(rootDir, 'dist', 'index.html');

if (!fs.existsSync(distHtmlPath)) {
  throw new Error(`Expected singlefile output at ${distHtmlPath}`);
}

const raw = fs.readFileSync(distHtmlPath, 'utf8').replace(/[ \t]+$/gm, '');
const normalized = `${raw.trimEnd()}\n`;
fs.writeFileSync(distHtmlPath, normalized, 'utf8');
