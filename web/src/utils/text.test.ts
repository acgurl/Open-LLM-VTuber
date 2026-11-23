import { describe, expect, it } from 'vitest';
import {
  backgroundUrl,
  buildTagSet,
  splitByTags,
  splitThink,
  stripTags,
} from './text';

describe('buildTagSet', () => {
  it('collects emotionMap and motionMap keys case-insensitively', () => {
    const tags = buildTagSet({
      emotionMap: { Joy: 1, SAD: 2 },
      motionMap: { Wave: { group: 'TapBody', index: 0 } },
    });
    expect(tags).toEqual(new Set(['joy', 'sad', 'wave']));
  });

  it('returns empty set for null or undefined model info', () => {
    expect(buildTagSet(null).size).toBe(0);
    expect(buildTagSet(undefined).size).toBe(0);
  });
});

describe('splitByTags and stripTags', () => {
  const tags = new Set(['joy', 'wave']);

  it('splits known tags while keeping unknown bracketed text literal', () => {
    expect(splitByTags('Hello [JOY] [unknown] [ wave ]!', tags)).toEqual([
      { kind: 'text', value: 'Hello ' },
      { kind: 'tag', value: 'joy' },
      { kind: 'text', value: ' [unknown] ' },
      { kind: 'tag', value: 'wave' },
      { kind: 'text', value: '!' },
    ]);
  });

  it('returns empty array for empty text and single text token when tagSet is empty', () => {
    expect(splitByTags('', tags)).toEqual([]);
    expect(splitByTags('Hi [joy]', new Set())).toEqual([
      { kind: 'text', value: 'Hi [joy]' },
    ]);
  });

  it('strips known tags and collapses repeated spaces', () => {
    expect(stripTags('Hello [joy]   world [wave]!', tags)).toBe('Hello world !');
    expect(stripTags('[joy] Hi [unknown]', tags)).toBe('Hi [unknown]');
  });
});

describe('splitThink', () => {
  it('splits closed and unclosed think blocks case-insensitively', () => {
    expect(splitThink('<THINK>plan</think>Answer<think>streaming')).toEqual([
      { kind: 'think', text: 'plan', closed: true },
      { kind: 'normal', text: 'Answer' },
      { kind: 'think', text: 'streaming', closed: false },
    ]);
  });

  it('handles plain text without think tags', () => {
    expect(splitThink('plain text')).toEqual([
      { kind: 'normal', text: 'plain text' },
    ]);
    expect(splitThink('')).toEqual([]);
  });
});

describe('backgroundUrl', () => {
  it('prefixes filenames with /bg/', () => {
    expect(backgroundUrl('room.png')).toBe('/bg/room.png');
  });
});
