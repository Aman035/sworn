/**
 * sworn-sdk — build SwornRouter calldata from a quote.
 *
 * Phase 8 fills in `buildSwornCall`, the quote adapters and the viem action. Until then this
 * module only exports the chain set the rest of the repo agrees on, so that consumers can
 * already pin against it.
 */

export const SDK_VERSION = '0.0.0';

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
