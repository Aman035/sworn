/**
 * Agent quickstart — swap through Sworn, refusing hooks above a score.
 *
 * The guarantee an agent needs is that the price it was shown is the price it gets.
 * `SwornRouter` provides that unconditionally: it probes every candidate inside the same
 * transaction that executes, and reverts if the executed amount differs from the probed
 * one. Nothing below is load-bearing for that — the score ceiling only avoids paying gas
 * to probe hooks already measured as bad.
 *
 *   pnpm --filter sworn-sdk exec tsx examples/agent-swap.ts
 */

import { createPublicClient, createWalletClient, http } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { base } from 'viem/chains';

import { HookBookReader, SwornPolicyError, prepareSwornSwap } from '../src/index.js';
import type { Address, Candidate } from '../src/index.js';

const RPC = process.env.BASE_RPC_ARCHIVE ?? 'https://mainnet.base.org';
const ROUTER = (process.env.SWORN_ROUTER ??
  '0x0000000000000000000000000000000000000000') as Address;
const HOOK_BOOK = (process.env.HOOKBOOK_ADDRESS_BASE ??
  '0x0000000000000000000000000000000000000000') as Address;

const WETH = '0x4200000000000000000000000000000000000006' as Address;
const USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913' as Address;

/**
 * In production these come from the index: every pool for the pair, hooked and hookless.
 * Passing more candidates is always safe — `testFuzz_moreCandidatesNeverHurts` asserts the
 * output can only improve — and the SDK rejects a set whose routes do not share the same
 * input and output tokens.
 */
function candidates(): Candidate[] {
  const hookless = {
    currency0: WETH < USDC ? WETH : USDC,
    currency1: WETH < USDC ? USDC : WETH,
    fee: 500,
    tickSpacing: 10,
    hooks: '0x0000000000000000000000000000000000000000' as Address,
  };
  return [{ hops: [{ key: hookless, zeroForOne: hookless.currency0 === WETH, hookData: '0x' }] }];
}

async function main(): Promise<void> {
  const transport = http(RPC);
  const publicClient = createPublicClient({ chain: base, transport });

  const key = process.env.AGENT_PK;
  if (!key) {
    console.error('set AGENT_PK to a funded key on Base');
    process.exit(1);
  }
  const account = privateKeyToAccount(key as `0x${string}`);
  const wallet = createWalletClient({ account, chain: base, transport });

  const hookBook = new HookBookReader(publicClient, HOOK_BOOK, {
    // A score older than an hour is treated as no score at all. Falling back to the last
    // known good value is what an attacker who could stall the attestor would want.
    maxAgeSeconds: 3_600n,
  });

  try {
    const call = await prepareSwornSwap({
      router: ROUTER,
      tokenIn: WETH,
      tokenOut: USDC,
      amount: 10n ** 16n, // 0.01 WETH
      minOut: 0n, // the probe is the protection; minOut is a backstop
      recipient: account.address,
      candidates: candidates(),
      // Refuse hooks measured above 20/100. Unscored hooks are refused too.
      maxHookScore: 20,
      hookBook,
    });

    const hash = await wallet.sendTransaction(call);
    console.log('sent:', hash);

    const receipt = await publicClient.waitForTransactionReceipt({ hash });
    console.log('status:', receipt.status);
    // A `Sworn` event carries the probed and executed amounts; they are equal by
    // construction, because the router reverts otherwise.
    console.log('logs:', receipt.logs.length);
  } catch (err) {
    if (err instanceof SwornPolicyError) {
      console.error('no acceptable route:', err.message);
      for (const r of err.rejected) console.error(`  ${r.hook}: ${r.reason}`);
      process.exit(2);
    }
    throw err;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
