import { swornRouterAbi } from './abi.js';
import { buildSwornCall, type BuildSwornCallArgs } from './buildCall.js';
import { HookBookReader } from './hookbook.js';
import { candidateIsHooked } from './buildCall.js';
import type { Address, Candidate, Hex, SwornCall } from './types.js';

/**
 * The narrow slice of a viem wallet/public client this package needs.
 *
 * Declared structurally rather than importing viem's `WalletClient` so the SDK does not
 * pin a viem major version on its consumers. Anything shaped like this works, including
 * an ethers adapter.
 */
export interface WriteClient {
  sendTransaction: (args: { to: Address; data: Hex; value: bigint }) => Promise<Hex>;
}

export interface SimulateClient {
  call: (args: { to: Address; data: Hex; value: bigint }) => Promise<{ data?: Hex }>;
}

export interface SwornSwapArgs extends BuildSwornCallArgs {
  /** Reject any candidate whose hook scores above this. Requires `hookBook`. */
  maxHookScore?: number;
  hookBook?: HookBookReader;
}

export class SwornPolicyError extends Error {
  constructor(
    message: string,
    readonly rejected: { hook: Address; reason: string }[],
  ) {
    super(message);
  }
}

function hooksOf(candidates: Candidate[]): Address[] {
  const seen = new Set<string>();
  const out: Address[] = [];
  for (const candidate of candidates) {
    for (const hop of candidate.hops) {
      const hook = hop.key.hooks;
      if (hook !== '0x0000000000000000000000000000000000000000' && !seen.has(hook.toLowerCase())) {
        seen.add(hook.toLowerCase());
        out.push(hook);
      }
    }
  }
  return out;
}

/**
 * Drop candidates whose hooks fail a score ceiling.
 *
 * This is a gas optimisation and a policy knob, **not** a safety mechanism. `SwornRouter`
 * already guarantees that what executes equals what was probed, whatever the score says.
 * Filtering here only avoids paying to probe hooks already known to be bad — and an
 * unscored or stale hook is rejected rather than waved through, because a caller who asks
 * for evidence and gets none has not been given a reason to proceed.
 */
export async function filterByScore(
  candidates: Candidate[],
  reader: HookBookReader,
  maxScore: number,
): Promise<{ kept: Candidate[]; rejected: { hook: Address; reason: string }[] }> {
  const rejected: { hook: Address; reason: string }[] = [];
  const blocked = new Set<string>();

  for (const hook of hooksOf(candidates)) {
    const verdict = await reader.isAcceptable(hook, maxScore);
    if (!verdict.ok) {
      rejected.push({ hook, reason: verdict.reason });
      blocked.add(hook.toLowerCase());
    }
  }

  const kept = candidates.filter(
    (c) => !c.hops.some((h) => blocked.has(h.key.hooks.toLowerCase())),
  );
  return { kept, rejected };
}

/** Build a Sworn call, optionally filtering candidates by `HookBook` score first. */
export async function prepareSwornSwap(args: SwornSwapArgs): Promise<SwornCall> {
  let candidates = args.candidates;

  if (args.maxHookScore !== undefined) {
    if (!args.hookBook) {
      throw new SwornPolicyError('maxHookScore requires a hookBook reader', []);
    }
    const { kept, rejected } = await filterByScore(candidates, args.hookBook, args.maxHookScore);
    if (kept.length === 0) {
      throw new SwornPolicyError(
        `every candidate was rejected by the score ceiling of ${args.maxHookScore}`,
        rejected,
      );
    }
    candidates = kept;
  }

  return buildSwornCall({ ...args, candidates });
}

/** Build and send. The returned hash is the swap transaction. */
export async function swornSwap(client: WriteClient, args: SwornSwapArgs): Promise<Hex> {
  const call = await prepareSwornSwap(args);
  return client.sendTransaction(call);
}

/** How many of the candidates carry a hook. Useful for logging and for tests. */
export function hookedCandidateCount(candidates: Candidate[]): number {
  return candidates.filter(candidateIsHooked).length;
}

export { swornRouterAbi };
