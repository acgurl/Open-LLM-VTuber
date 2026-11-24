import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { DECK_SOURCE } from '../data/deck.ts';
import { generateDocs } from './docGenerator.ts';

const defenseRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function normalizeLf(text: string): string {
  return text.replace(/\r\n/g, '\n');
}

describe('generateDocs (Seam 2: single-source document generator)', () => {
  it('generates speechScriptMd with updated 1:10 / 2:25 / 4:10 anchors, all 6 slides, and zero stale video/anchor copy', () => {
    const { speechScriptMd } = generateDocs(DECK_SOURCE);

    expect(speechScriptMd).toContain('4 分 50 秒（290 秒）');
    for (const anchor of DECK_SOURCE.anchors) {
      expect(speechScriptMd).toContain(anchor.timeLabel);
      expect(speechScriptMd).toContain(anchor.rescueStrategy);
    }
    for (const slide of DECK_SOURCE.slides) {
      expect(speechScriptMd).toContain(`Slide ${slide.id}`);
      expect(speechScriptMd).toContain(slide.title);
      for (const seg of slide.scriptSegments) {
        expect(speechScriptMd).toContain(seg.text);
      }
    }

    for (const forbidden of ['1:40', '2:30', '4:20', 'demo.mp4', '实录视频', '离线模拟', '三层兜底']) {
      expect(speechScriptMd).not.toContain(forbidden);
    }
  });

  it('generates demoGuideMd with live endpoints, 5 prompts, 6 Q&As, deploy command, and zero video/offline-sim copy', () => {
    const { demoGuideMd } = generateDocs(DECK_SOURCE);

    expect(demoGuideMd).toContain(DECK_SOURCE.meta.sameOriginDeployUrl);
    expect(demoGuideMd).toContain(DECK_SOURCE.meta.deployPowerShellCmd);
    for (const ep of DECK_SOURCE.slide3.endpoints) {
      expect(demoGuideMd).toContain(ep.url);
    }
    for (const prompt of DECK_SOURCE.slide3.prompts) {
      expect(demoGuideMd).toContain(prompt.prompt);
    }
    for (const qa of DECK_SOURCE.qaItems) {
      expect(demoGuideMd).toContain(qa.q);
      expect(demoGuideMd).toContain(qa.a);
    }

    for (const forbidden of ['demo.mp4', '实录视频', '离线模拟', '三层兜底']) {
      expect(demoGuideMd).not.toContain(forbidden);
    }
  });

  it('matches on-disk defense/speech_script.md and defense/demo_guide.md with zero drift', () => {
    const generated = generateDocs(DECK_SOURCE);
    const diskSpeech = normalizeLf(
      fs.readFileSync(path.join(defenseRoot, 'speech_script.md'), 'utf8'),
    );
    const diskGuide = normalizeLf(
      fs.readFileSync(path.join(defenseRoot, 'demo_guide.md'), 'utf8'),
    );

    expect(diskSpeech).toBe(generated.speechScriptMd);
    expect(diskGuide).toBe(generated.demoGuideMd);
  });
});
