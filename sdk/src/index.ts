/**
 * sworn-sdk — build `SwornRouter` calldata, and read `HookBook` scores.
 *
 * The router's guarantee does not depend on anything in this package: a swap routed
 * through `SwornRouter` cannot be served a price different from the one that executes,
 * whatever the SDK does. What the SDK adds is a candidate set that is coherent, and a way
 * to read the advisory scores.
 */

export { swornRouterAbi, hookBookAbi } from './abi.js';
export {
  buildSwornCall,
  candidateIsHooked,
  isHooked,
  isNative,
  validateCandidates,
  SwornSdkError,
  DEFAULT_DEADLINE_SECONDS,
  DEFAULT_HOOK_MARGIN_BPS,
  DEFAULT_MAX_PROBES,
  DEFAULT_PROBE_GAS,
  type BuildSwornCallArgs,
} from './buildCall.js';
export {
  HookBookReader,
  explain,
  explainFlags,
  type HookScore,
  type HookBookReaderOptions,
  type ReadClient,
} from './hookbook.js';
export {
  ADDRESS_ZERO,
  DYNAMIC_FEE_FLAG,
  HOOK_FLAGS,
  type Address,
  type Candidate,
  type Hex,
  type Hop,
  type HookFlagName,
  type PoolKey,
  type SwornCall,
  type SwornParams,
} from './types.js';

export const SDK_VERSION = '0.1.0';

/** Chains Sworn targets, in the build-priority order used across the repo. */
export const SWORN_CHAINS = {
  base: 8453,
  bnb: 56,
  arbitrum: 42161,
  unichain: 130,
  mainnet: 1,
  polygon: 137,
} as const;

export type SwornChainName = keyof typeof SWORN_CHAINS;
export type SwornChainId = (typeof SWORN_CHAINS)[SwornChainName];

export function chainIdFor(name: SwornChainName): SwornChainId {
  return SWORN_CHAINS[name];
}
