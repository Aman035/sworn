import { describe, expect, it, vi } from 'vitest';

import { HOOK_FLAGS, HookBookReader, explain, explainFlags } from '../src/index.js';
import type { Address } from '../src/index.js';

const BOOK: Address = '0x9999999999999999999999999999999999999999';
const HOOK: Address = '0x800cef53c3fd41109dffec62e5251bdd7acba5c7';

function client(score: number, flags: number, scored: boolean, ageSeconds = 60n) {
  return {
    readContract: vi.fn(async ({ functionName }: { functionName: string }) => {
      if (functionName === 'scoreWithAge') return [score, ageSeconds, scored];
      if (functionName === 'flags') return flags;
      throw new Error(`unexpected call ${functionName}`);
    }),
  };
}

describe('explainFlags', () => {
  it('lists set flags in bit order', () => {
    expect(explainFlags(HOOK_FLAGS.DIVERGENT | HOOK_FLAGS.INTERMITTENT)).toEqual([
      'DIVERGENT',
      'INTERMITTENT',
    ]);
  });

  it('returns nothing for a clean word', () => {
    expect(explainFlags(0)).toEqual([]);
  });
});

describe('explain', () => {
  it('distinguishes never-measured from measured-clean', () => {
    const unmeasured = explain({ hook: HOOK, score: 0, flags: 0, scored: false, ageSeconds: 0n });
    const clean = explain({ hook: HOOK, score: 0, flags: 0, scored: true, ageSeconds: 0n });

    // These two must never read the same: a low score only means something if absence
    // is reported as absence.
    expect(unmeasured).toMatch(/never measured/);
    expect(clean).toBe('score 0/100');
    expect(unmeasured).not.toBe(clean);
  });

  it('names the flags that are set', () => {
    const out = explain({
      hook: HOOK,
      score: 67,
      flags: HOOK_FLAGS.DIVERGENT | HOOK_FLAGS.ENV_SENSITIVE,
      scored: true,
      ageSeconds: 0n,
    });
    expect(out).toContain('67/100');
    expect(out).toContain('DIVERGENT');
    expect(out).toContain('ENV_SENSITIVE');
  });
});

describe('HookBookReader', () => {
  it('reads a score', async () => {
    const reader = new HookBookReader(client(42, HOOK_FLAGS.ENV_SENSITIVE, true), BOOK);
    const result = await reader.get(HOOK);
    expect(result.score).toBe(42);
    expect(result.scored).toBe(true);
  });

  it('caches within the ttl and refetches after it', async () => {
    const c = client(10, 0, true);
    const reader = new HookBookReader(c, BOOK, { cacheTtlMs: 10_000 });

    await reader.get(HOOK);
    await reader.get(HOOK);
    expect(c.readContract).toHaveBeenCalledTimes(2); // scoreWithAge + flags, once

    reader.clearCache();
    await reader.get(HOOK);
    expect(c.readContract).toHaveBeenCalledTimes(4);
  });

  it('rejects an unscored hook when a ceiling is requested', async () => {
    const reader = new HookBookReader(client(0, HOOK_FLAGS.INSUFFICIENT_DATA, false), BOOK);
    const verdict = await reader.isAcceptable(HOOK, 20);

    // The caller asked for evidence and there is none; silently passing would turn an
    // unmeasured hook into an endorsed one.
    expect(verdict.ok).toBe(false);
    expect(verdict.reason).toMatch(/no score/);
  });

  it('accepts a hook under the ceiling', async () => {
    const reader = new HookBookReader(client(5, 0, true), BOOK);
    expect((await reader.isAcceptable(HOOK, 20)).ok).toBe(true);
  });

  it('rejects a hook above the ceiling', async () => {
    const reader = new HookBookReader(client(67, HOOK_FLAGS.DIVERGENT, true), BOOK);
    const verdict = await reader.isAcceptable(HOOK, 20);
    expect(verdict.ok).toBe(false);
    expect(verdict.reason).toMatch(/exceeds the ceiling/);
  });

  it('treats a stale score as no score', async () => {
    const reader = new HookBookReader(client(5, 0, true, 90_000n), BOOK, { maxAgeSeconds: 3_600n });
    const verdict = await reader.isAcceptable(HOOK, 20);

    // Falling back to "last known good" is exactly what an attacker who can stall the
    // attestor would want.
    expect(verdict.ok).toBe(false);
    expect(verdict.reason).toMatch(/old/);
  });
});
