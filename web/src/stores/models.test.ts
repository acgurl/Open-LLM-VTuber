import { beforeEach, describe, expect, it } from 'vitest';
import { useModels } from './models';

type Catalogs = ReturnType<typeof useModels.getState>['catalogs'];

const initialCatalogs = (): Catalogs => ({
  llm: {
    options: [
      {
        id: 'reasoner',
        name: 'Reasoner',
        description: '',
        thinking: {
          levels: [
            { id: 'off', name: 'Off' },
            { id: 'medium', name: 'Medium' },
            { id: 'high', name: 'High' },
          ],
          default: 'medium',
        },
      },
    ],
    current: 'reasoner',
    characterDefault: { id: 'char-llm', name: 'Char LLM', description: '' },
  },
  tts: { options: [], current: null },
  asr: { options: [], current: null },
});

describe('useModels store', () => {
  beforeEach(() => {
    useModels.setState({
      catalogs: {
        llm: { options: [], current: null },
        tts: { options: [], current: null },
        asr: { options: [], current: null },
      },
      pending: null,
      thinking: null,
      lastThinkingOn: {},
    });
  });

  it('tracks thinking level and remembers last non-off level per model', () => {
    useModels.getState().setList(initialCatalogs(), 'medium');
    expect(useModels.getState().thinking).toBe('medium');
    expect(useModels.getState().lastThinkingOn).toEqual({ reasoner: 'medium' });

    useModels.getState().setThinking('high');
    expect(useModels.getState().lastThinkingOn).toEqual({ reasoner: 'high' });

    useModels.getState().setThinking('off');
    expect(useModels.getState().thinking).toBe('off');
    expect(useModels.getState().lastThinkingOn).toEqual({ reasoner: 'high' });
  });

  it('falls back to characterDefault id when current llm is null', () => {
    const catalogs = initialCatalogs();
    catalogs.llm.current = null;
    useModels.getState().setList(catalogs, 'medium');
    expect(useModels.getState().lastThinkingOn).toEqual({ 'char-llm': 'medium' });
  });

  it('clears pending only for matching kind on confirmSwitch and preserves others', () => {
    useModels.getState().setList(initialCatalogs(), 'medium');
    useModels.getState().requestSwitch({ kind: 'tts', id: 'azure-xiaoyi' });

    useModels.getState().confirmSwitch('llm', 'other-llm', 'low');
    expect(useModels.getState().pending).toEqual({ kind: 'tts', id: 'azure-xiaoyi' });
    expect(useModels.getState().catalogs.llm.current).toBe('other-llm');
    expect(useModels.getState().thinking).toBe('low');

    useModels.getState().confirmSwitch('tts', 'azure-xiaoyi', null);
    expect(useModels.getState().pending).toBeNull();
    expect(useModels.getState().catalogs.tts.current).toBe('azure-xiaoyi');
    // Confirming TTS switch must not wipe LLM thinking state.
    expect(useModels.getState().thinking).toBe('low');
  });

  it('cancels pending switch only when kind matches or is omitted', () => {
    useModels.getState().requestSwitch({ kind: 'asr', id: 'groq-whisper' });
    useModels.getState().cancelSwitch('llm');
    expect(useModels.getState().pending).toEqual({ kind: 'asr', id: 'groq-whisper' });

    useModels.getState().cancelSwitch('asr');
    expect(useModels.getState().pending).toBeNull();

    useModels.getState().requestSwitch({ kind: 'tts', id: 'edge' });
    useModels.getState().cancelSwitch();
    expect(useModels.getState().pending).toBeNull();
  });
});
