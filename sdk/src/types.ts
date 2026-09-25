/**
 * Types mirroring `contracts/src/SwornRouter.sol`.
 *
 * These are hand-written rather than generated so the SDK has no build-time dependency on
 * a Foundry artifact. The golden-calldata tests encode the same structs with viem and
 * compare against Foundry output, so a drift between this file and the contract fails the
 * suite rather than shipping.
 */

export type Address = `0x${string}`;
export type Hex = `0x${string}`;

/** A v4 pool's identity. `currency0 < currency1`, and the hook address carries its own permissions. */
export interface PoolKey {
  currency0: Address;
  currency1: Address;
  /** Hundredths of a bip. `0x800000` is the dynamic-fee sentinel. */
  fee: number;
  tickSpacing: number;
  hooks: Address;
}

/** One leg of a route. */
export interface Hop {
  key: PoolKey;
  zeroForOne: boolean;
  hookData: Hex;
}

/** A candidate route: single- or multi-hop. */
export interface Candidate {
  hops: Hop[];
}

export interface SwornParams {
  tokenIn: Address;
  tokenOut: Address;
  /** v4 convention: negative is exact-input, positive is exact-output. */
  amountSpecified: bigint;
  /** Exact-in: minimum output. Exact-out: maximum input. */
  minOut: bigint;
  /** A hooked route must beat the best hookless route by this margin to be chosen. */
  hookMarginBps: number;
  /** Identical gas stipend for every probe and for the execution. */
  probeGas: bigint;
  maxProbes: number;
  recipient: Address;
  deadline: bigint;
  usePermit2: boolean;
  permit: Hex;
}

export interface SwornCall {
  to: Address;
  data: Hex;
  value: bigint;
}

export const DYNAMIC_FEE_FLAG = 0x800000;
export const ADDRESS_ZERO: Address = '0x0000000000000000000000000000000000000000';

/** The flags word `HookBook` stores. Bit positions are frozen; see analysis/config.yaml. */
export const HOOK_FLAGS = {
  DIVERGENT: 1 << 0,
  ENV_SENSITIVE: 1 << 1,
  INTERMITTENT: 1 << 2,
  UPGRADEABLE: 1 << 3,
  OWNER_SWITCHED: 1 << 4,
  REVERT_GATED: 1 << 5,
  DYNAMIC_FEE: 1 << 6,
  RETURNS_DELTA: 1 << 7,
  ALLOWLISTED: 1 << 8,
  VERIFIED: 1 << 9,
  INSUFFICIENT_DATA: 1 << 10,
} as const;

export type HookFlagName = keyof typeof HOOK_FLAGS;
