import { describe, expect, it, vi } from 'vitest';

import {
  HookBookReader,
  HOOK_FLAGS,
  SwornPolicyError,
  filterByScore,
  hookedCandidateCount,
  prepareSwornSwap,
  swornSwap,
} from '../src/index.js';
import type { Address, Candidate, PoolKey } from '../src/index.js';

const ROUTER: Address = '0x1111111111111111111111111111111111111111';
const TOKEN_A: Address = '0x2222222222222222222222222222222222222222';
const TOKEN_B: Address = '0x3333333333333333333333333333333333333333';
const CLEAN_HOOK: Address = '0x5555555555555555555555555555555555550088';
const NASTY_HOOK: Address = '0x6666666666666666666666666666666666660088';
const BOOK: Address = '0x9999999999999999999999999999999999999999';
const USER: Address = '0x7777777777777777777777777777777777777777';
const ZERO: Address = '0x0000000000000000000000000000000000000000';

function key(hooks: Address = ZERO): PoolKey {
  const [c0, c1] = TOKEN_A < TOKEN_B ? [TOKEN_A, TOKEN_B] : [TOKEN_B, TOKEN_A];
  return { currency0: c0, currency1: c1, fee: 3000, tickSpacing: 60, hooks };
}

function candidate(hooks: Address = ZERO): Candidate {
  const k = key(hooks);
  return {
    hops: [{ key: k, zeroForOne: k.currency0 === TOKEN_A, hookData: '0x' }],
  };
}

/** A HookBook whose answers are dictated per hook. */
function reader(scores: Record<string, { score: number; scored: boolean; age?: bigint }>) {
  const client = {
    readContract: vi.fn(
      async ({ functionName, args }: { functionName: string; args: readonly unknown[] }) => {
        const hook = String(args[0]).toLowerCase();
        const entry = scores[hook] ?? { score: 0, scored: false };
        if (functionName === 'scoreWithAge') return [entry.score, entry.age ?? 10n, entry.scored];
        if (functionName === 'flags') return entry.scored ? 0 : HOOK_FLAGS.INSUFFICIENT_DATA;
        throw new Error(functionName);
      },
    ),
  };
  return new HookBookReader(client, BOOK);
}

const base = {
  router: ROUTER,
  tokenIn: TOKEN_A,
  tokenOut: TOKEN_B,
  amount: 10n ** 18n,
  minOut: 0n,
  recipient: USER,
  now: () => 1_000_000n,
};

describe('filterByScore', () => {
  it('keeps candidates under the ceiling and drops those over it', async () => {
    const r = reader({
      [CLEAN_HOOK.toLowerCase()]: { score: 5, scored: true },
      [NASTY_HOOK.toLowerCase()]: { score: 80, scored: true },
    });

    const { kept, rejected } = await filterByScore(
      [candidate(), candidate(CLEAN_HOOK), candidate(NASTY_HOOK)],
      r,
      20,
    );

    expect(kept).toHaveLength(2);
    expect(rejected).toHaveLength(1);
    expect(rejected[0]!.hook).toBe(NASTY_HOOK);
  });

  it('never drops a hookless candidate', async () => {
    const r = reader({});
    const { kept } = await filterByScore([candidate()], r, 0);
    expect(kept).toHaveLength(1);
  });

  it('rejects unscored hooks when a ceiling is requested', async () => {
    // The caller asked for evidence and there is none. Passing it through would turn an
    // unmeasured hook into an endorsed one.
    const r = reader({});
    const { kept, rejected } = await filterByScore([candidate(CLEAN_HOOK)], r, 50);
    expect(kept).toHaveLength(0);
    expect(rejected[0]!.reason).toMatch(/no score/);
  });
});

describe('prepareSwornSwap', () => {
  it('builds a call without a ceiling', async () => {
    const call = await prepareSwornSwap({ ...base, candidates: [candidate()] });
    expect(call.to).toBe(ROUTER);
    expect(call.data.startsWith('0x')).toBe(true);
  });

  it('requires a reader when a ceiling is given', async () => {
    await expect(
      prepareSwornSwap({ ...base, candidates: [candidate()], maxHookScore: 20 }),
    ).rejects.toThrow(SwornPolicyError);
  });

  it('throws when the ceiling removes every candidate', async () => {
    const r = reader({ [NASTY_HOOK.toLowerCase()]: { score: 90, scored: true } });
    await expect(
      prepareSwornSwap({
        ...base,
        candidates: [candidate(NASTY_HOOK)],
        maxHookScore: 20,
        hookBook: r,
      }),
    ).rejects.toThrow(/every candidate was rejected/);
  });

  it('carries the rejection reasons on the error', async () => {
    const r = reader({ [NASTY_HOOK.toLowerCase()]: { score: 90, scored: true } });
    try {
      await prepareSwornSwap({
        ...base,
        candidates: [candidate(NASTY_HOOK)],
        maxHookScore: 20,
        hookBook: r,
      });
      throw new Error('should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(SwornPolicyError);
      expect((err as SwornPolicyError).rejected[0]!.reason).toMatch(/exceeds the ceiling/);
    }
  });

  it('keeps the hookless fallback when the hooked candidate is rejected', async () => {
    const r = reader({ [NASTY_HOOK.toLowerCase()]: { score: 90, scored: true } });
    const call = await prepareSwornSwap({
      ...base,
      candidates: [candidate(NASTY_HOOK), candidate()],
      maxHookScore: 20,
      hookBook: r,
    });
    expect(call.to).toBe(ROUTER);
  });
});

describe('swornSwap', () => {
  it('sends the built call', async () => {
    const sent: { to: Address; value: bigint }[] = [];
    const client = {
      sendTransaction: vi.fn(async (call: { to: Address; data: `0x${string}`; value: bigint }) => {
        sent.push({ to: call.to, value: call.value });
        return '0xdeadbeef' as const;
      }),
    };

    const hash = await swornSwap(client, { ...base, candidates: [candidate()] });

    expect(hash).toBe('0xdeadbeef');
    expect(sent).toHaveLength(1);
    expect(sent[0]!.to).toBe(ROUTER);
    expect(sent[0]!.value).toBe(0n);
  });
});

describe('hookedCandidateCount', () => {
  it('counts only hooked candidates', () => {
    expect(hookedCandidateCount([candidate(), candidate(CLEAN_HOOK)])).toBe(1);
  });
});
