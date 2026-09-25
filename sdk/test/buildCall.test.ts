import { describe, expect, it } from 'vitest';
import { decodeFunctionData } from 'viem';

import {
  ADDRESS_ZERO,
  DEFAULT_HOOK_MARGIN_BPS,
  SwornSdkError,
  buildSwornCall,
  candidateIsHooked,
  swornRouterAbi,
  validateCandidates,
} from '../src/index.js';
import type { Address, Candidate, Hex, PoolKey } from '../src/index.js';

/** Decode the params struct back out of built calldata, typed by the ABI. */
function decodeParams(data: Hex) {
  return decodeFunctionData({ abi: swornRouterAbi, data }).args[1];
}

const ROUTER: Address = '0x1111111111111111111111111111111111111111';
const TOKEN_A: Address = '0x2222222222222222222222222222222222222222';
const TOKEN_B: Address = '0x3333333333333333333333333333333333333333';
const TOKEN_C: Address = '0x4444444444444444444444444444444444444444';
const HOOK: Address = '0x5555555555555555555555555555555555550088';
const USER: Address = '0x6666666666666666666666666666666666666666';

function poolKey(a: Address, b: Address, hooks: Address = ADDRESS_ZERO): PoolKey {
  const [currency0, currency1] = a.toLowerCase() < b.toLowerCase() ? [a, b] : [b, a];
  return { currency0, currency1, fee: 3000, tickSpacing: 60, hooks };
}

function hop(a: Address, b: Address, hooks: Address = ADDRESS_ZERO) {
  const key = poolKey(a, b, hooks);
  return {
    key,
    zeroForOne: key.currency0.toLowerCase() === a.toLowerCase(),
    hookData: '0x' as const,
  };
}

function single(a: Address, b: Address, hooks: Address = ADDRESS_ZERO): Candidate {
  return { hops: [hop(a, b, hooks)] };
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

describe('buildSwornCall', () => {
  it('encodes a call the router ABI can decode back', () => {
    const call = buildSwornCall({ ...base, candidates: [single(TOKEN_A, TOKEN_B)] });

    expect(call.to).toBe(ROUTER);
    expect(call.value).toBe(0n);

    const decoded = decodeFunctionData({ abi: swornRouterAbi, data: call.data });
    expect(decoded.functionName).toBe('swornSwap');
  });

  it('encodes exact-input as a negative amount', () => {
    const call = buildSwornCall({ ...base, candidates: [single(TOKEN_A, TOKEN_B)] });
    const params = decodeParams(call.data);
    // v4 puts the direction in the sign; getting this backwards silently swaps the
    // meaning of the trade.
    expect(params.amountSpecified).toBe(-(10n ** 18n));
  });

  it('encodes exact-output as a positive amount', () => {
    const call = buildSwornCall({
      ...base,
      candidates: [single(TOKEN_A, TOKEN_B)],
      exactOut: true,
    });
    const params = decodeParams(call.data);
    expect(params.amountSpecified).toBe(10n ** 18n);
  });

  it('defaults to a non-zero hook margin', () => {
    const call = buildSwornCall({ ...base, candidates: [single(TOKEN_A, TOKEN_B)] });
    const params = decodeParams(call.data);
    // A hooked route carries more ways to fail, so equal pricing should not win it.
    expect(params.hookMarginBps).toBe(DEFAULT_HOOK_MARGIN_BPS);
    expect(DEFAULT_HOOK_MARGIN_BPS).toBeGreaterThan(0);
  });

  it('sends native input as msg.value', () => {
    const call = buildSwornCall({
      ...base,
      tokenIn: ADDRESS_ZERO,
      candidates: [single(ADDRESS_ZERO, TOKEN_B)],
    });
    expect(call.value).toBe(10n ** 18n);
  });

  it('refuses exact-out with native input unless a value bound is given', () => {
    expect(() =>
      buildSwornCall({
        ...base,
        tokenIn: ADDRESS_ZERO,
        exactOut: true,
        candidates: [single(ADDRESS_ZERO, TOKEN_B)],
      }),
    ).toThrow(SwornSdkError);
  });

  it('rejects a non-positive amount', () => {
    expect(() =>
      buildSwornCall({ ...base, amount: 0n, candidates: [single(TOKEN_A, TOKEN_B)] }),
    ).toThrow(/amount must be positive/);
  });

  it('uses a relative deadline by default', () => {
    const call = buildSwornCall({ ...base, candidates: [single(TOKEN_A, TOKEN_B)] });
    const params = decodeParams(call.data);
    expect(params.deadline).toBe(1_000_600n);
  });
});

describe('validateCandidates', () => {
  it('accepts a coherent set', () => {
    expect(() =>
      validateCandidates(
        [single(TOKEN_A, TOKEN_B), single(TOKEN_A, TOKEN_B, HOOK)],
        TOKEN_A,
        TOKEN_B,
      ),
    ).not.toThrow();
  });

  it('rejects an empty set', () => {
    expect(() => validateCandidates([], TOKEN_A, TOKEN_B)).toThrow(/no candidates/);
  });

  it('rejects a route that ends in the wrong token', () => {
    // The router compares probed outputs as raw numbers. Two routes ending in different
    // tokens would be compared as if they were the same unit — the most dangerous
    // malformed input there is, so it must never reach the chain.
    expect(() => validateCandidates([single(TOKEN_A, TOKEN_C)], TOKEN_A, TOKEN_B)).toThrow(
      /ends in .*not tokenOut/,
    );
  });

  it('rejects a route that starts in the wrong token', () => {
    expect(() => validateCandidates([single(TOKEN_C, TOKEN_B)], TOKEN_A, TOKEN_B)).toThrow(
      /starts in .*not tokenIn/,
    );
  });

  it('rejects a disconnected multi-hop route', () => {
    const broken: Candidate = { hops: [hop(TOKEN_A, TOKEN_B), hop(TOKEN_C, TOKEN_B)] };
    expect(() => validateCandidates([broken], TOKEN_A, TOKEN_B)).toThrow(
      /takes .*but hop 0 produced/,
    );
  });

  it('accepts a connected multi-hop route', () => {
    const route: Candidate = { hops: [hop(TOKEN_A, TOKEN_C), hop(TOKEN_C, TOKEN_B)] };
    expect(() => validateCandidates([route], TOKEN_A, TOKEN_B)).not.toThrow();
  });

  it('rejects more candidates than the router can index', () => {
    const many = Array.from({ length: 256 }, () => single(TOKEN_A, TOKEN_B));
    expect(() => validateCandidates(many, TOKEN_A, TOKEN_B)).toThrow(/uint8/);
  });

  it('rejects a candidate with no hops', () => {
    expect(() => validateCandidates([{ hops: [] }], TOKEN_A, TOKEN_B)).toThrow(/no hops/);
  });
});

describe('candidateIsHooked', () => {
  it('detects a hooked leg anywhere in the route', () => {
    expect(candidateIsHooked(single(TOKEN_A, TOKEN_B))).toBe(false);
    expect(candidateIsHooked(single(TOKEN_A, TOKEN_B, HOOK))).toBe(true);
    expect(candidateIsHooked({ hops: [hop(TOKEN_A, TOKEN_C), hop(TOKEN_C, TOKEN_B, HOOK)] })).toBe(
      true,
    );
  });
});
