import { encodeFunctionData } from 'viem';

import { swornRouterAbi } from './abi.js';
import {
  ADDRESS_ZERO,
  type Address,
  type Candidate,
  type Hex,
  type PoolKey,
  type SwornCall,
  type SwornParams,
} from './types.js';

/** Default gas stipend handed to every probe and to the execution. */
export const DEFAULT_PROBE_GAS = 2_000_000n;

/**
 * How much better a hooked route must price to be chosen over the best hookless one.
 *
 * Not zero by default. A hooked route carries more ways to fail: a revert, a griefing
 * hook, more gas, so it should have to be usefully better, not merely equal. Integrators
 * who disagree can pass 0.
 */
export const DEFAULT_HOOK_MARGIN_BPS = 5;

export const DEFAULT_MAX_PROBES = 4;

/** Seconds a call stays valid if the caller gives no deadline. */
export const DEFAULT_DEADLINE_SECONDS = 600n;

export interface BuildSwornCallArgs {
  router: Address;
  tokenIn: Address;
  tokenOut: Address;
  /** Positive magnitude. Direction comes from `exactOut`. */
  amount: bigint;
  /** Exact-in: minimum output. Exact-out: maximum input. */
  minOut: bigint;
  recipient: Address;
  candidates: Candidate[];
  exactOut?: boolean;
  hookMarginBps?: number;
  probeGas?: bigint;
  maxProbes?: number;
  /** Absolute unix seconds. Defaults to now + `DEFAULT_DEADLINE_SECONDS`. */
  deadline?: bigint;
  permit2?: { permit: Hex } | undefined;
  /** Override the ETH sent. Defaults to `amount` when `tokenIn` is native and exact-in. */
  value?: bigint;
  now?: () => bigint;
}

export class SwornSdkError extends Error {}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new SwornSdkError(message);
}

export function isNative(currency: Address): boolean {
  return currency.toLowerCase() === ADDRESS_ZERO;
}

export function isHooked(key: PoolKey): boolean {
  return !isNative(key.hooks);
}

export function candidateIsHooked(candidate: Candidate): boolean {
  return candidate.hops.some((h) => isHooked(h.key));
}

/**
 * Validate a candidate set against what the router assumes.
 *
 * The router compares probed outputs directly; it has no way to know that two routes end
 * in different tokens. That makes a malformed candidate set the integrator's error, and
 * an unchecked one a real hazard, so it is rejected here rather than producing a
 * confidently wrong route on-chain.
 */
export function validateCandidates(
  candidates: Candidate[],
  tokenIn: Address,
  tokenOut: Address,
): void {
  assert(candidates.length > 0, 'no candidates: nothing to probe');
  assert(
    candidates.length <= 255,
    `too many candidates (${candidates.length}); the router indexes them as uint8`,
  );

  candidates.forEach((candidate, i) => {
    assert(candidate.hops.length > 0, `candidate ${i} has no hops`);

    const first = candidate.hops[0]!;
    const last = candidate.hops[candidate.hops.length - 1]!;
    const entry = first.zeroForOne ? first.key.currency0 : first.key.currency1;
    const exit = last.zeroForOne ? last.key.currency1 : last.key.currency0;

    assert(
      entry.toLowerCase() === tokenIn.toLowerCase(),
      `candidate ${i} starts in ${entry}, not tokenIn ${tokenIn}`,
    );
    assert(
      exit.toLowerCase() === tokenOut.toLowerCase(),
      `candidate ${i} ends in ${exit}, not tokenOut ${tokenOut}; ` +
        'the router compares probed outputs directly and cannot detect mismatched units',
    );

    // Intermediate legs must actually connect, or the route is not a route.
    for (let h = 1; h < candidate.hops.length; h++) {
      const prev = candidate.hops[h - 1]!;
      const cur = candidate.hops[h]!;
      const prevOut = prev.zeroForOne ? prev.key.currency1 : prev.key.currency0;
      const curIn = cur.zeroForOne ? cur.key.currency0 : cur.key.currency1;
      assert(
        prevOut.toLowerCase() === curIn.toLowerCase(),
        `candidate ${i} hop ${h} takes ${curIn} but hop ${h - 1} produced ${prevOut}`,
      );
    }
  });
}

/** Build the calldata for a `SwornRouter.swornSwap`. */
export function buildSwornCall(args: BuildSwornCallArgs): SwornCall {
  const {
    router,
    tokenIn,
    tokenOut,
    amount,
    minOut,
    recipient,
    candidates,
    exactOut = false,
    hookMarginBps = DEFAULT_HOOK_MARGIN_BPS,
    probeGas = DEFAULT_PROBE_GAS,
    maxProbes = DEFAULT_MAX_PROBES,
    deadline,
    permit2,
    value,
    now = () => BigInt(Math.floor(Date.now() / 1000)),
  } = args;

  assert(amount > 0n, 'amount must be positive; direction is set by `exactOut`');
  assert(probeGas > 0n, 'probeGas must be positive');
  assert(maxProbes > 0, 'maxProbes must be positive');
  assert(hookMarginBps >= 0 && hookMarginBps <= 65_535, 'hookMarginBps must fit a uint16');

  validateCandidates(candidates, tokenIn, tokenOut);

  const params: SwornParams = {
    tokenIn,
    tokenOut,
    // v4 encodes direction in the sign: negative is exact-input.
    amountSpecified: exactOut ? amount : -amount,
    minOut,
    hookMarginBps,
    probeGas,
    maxProbes,
    recipient,
    deadline: deadline ?? now() + DEFAULT_DEADLINE_SECONDS,
    usePermit2: permit2 !== undefined,
    permit: permit2?.permit ?? '0x',
  };

  const data = encodeFunctionData({
    abi: swornRouterAbi,
    functionName: 'swornSwap',
    args: [candidates, params],
  });

  // Native input is paid as msg.value. Exact-out cannot know the cost up front, so the
  // caller must say how much to send.
  let callValue = value ?? 0n;
  if (value === undefined && isNative(tokenIn)) {
    assert(!exactOut, 'exact-out with native input needs an explicit `value` upper bound');
    callValue = amount;
  }

  return { to: router, data, value: callValue };
}
