import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DECK_SOURCE } from '../src/data/deck.ts';
import { generateDocs } from '../src/core/docGenerator.ts';

const defenseRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { speechScriptMd, demoGuideMd } = generateDocs(DECK_SOURCE);

fs.writeFileSync(path.join(defenseRoot, 'speech_script.md'), speechScriptMd, 'utf8');
fs.writeFileSync(path.join(defenseRoot, 'demo_guide.md'), demoGuideMd, 'utf8');
console.log('Generated defense/speech_script.md and defense/demo_guide.md from DECK_SOURCE.');
