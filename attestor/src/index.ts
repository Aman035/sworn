/**
 * sworn-attestor — publish computed hook scores to `HookBook`.
 *
 * Run on a schedule (see `.github/workflows/attestor.yml`). Reads
 * `data/results/scores.json`, which a pipeline produced from a hashed snapshot, and
 * writes the scored hooks on-chain in batches.
 *
 * What it deliberately does not do:
 *
 * * **Invent scores.** It publishes what the pipeline computed and refuses a document
 *   with no snapshot provenance.
 * * **Publish unmeasured hooks.** A hook with too little evidence is skipped, so
 *   `HookBook` keeps reading `INSUFFICIENT_DATA` for it rather than a misleading 0.
 * * **Hold value.** The key needs only enough gas to write. `HookBook.setScoreWithSig`
 *   exists so even that can be delegated to a relayer.
 *
 *   pnpm --filter sworn-attestor start -- --chain base --dry-run
 */

import { createPublicClient, createWalletClient, http, type Address, type Hex } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

import {
  AttestorError,
  chunk,
  loadScores,
  publishable,
  snapshotHash,
  type ScoreRow,
} from './scores.js';

export { AttestorError, chunk, loadScores, publishable, snapshotHash };
export type { ScoreRow };

export const hookBookAbi = [
  {
    type: 'function',
    name: 'setScores',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'hooks', type: 'address[]' },
      { name: 'scores', type: 'uint8[]' },
      { name: 'flagsList', type: 'uint32[]' },
      { name: 'asOfBlock', type: 'uint64' },
      { name: 'snapshotHash', type: 'bytes32' },
    ],
    outputs: [],
  },
  {
    type: 'function',
    name: 'isAttestor',
    stateMutability: 'view',
    inputs: [{ name: 'attestor', type: 'address' }],
    outputs: [{ type: 'bool' }],
  },
] as const;

export const DEFAULT_BATCH_SIZE = 100;

export interface AttestOptions {
  chain: string;
  scoresPath: string;
  hookBook: Address;
  rpcUrl: string;
  privateKey?: Hex;
  batchSize?: number;
  dryRun?: boolean;
  log?: (message: string) => void;
}

export interface AttestReport {
  chain: string;
  total: number;
  publishable: number;
  batches: number;
  txHashes: Hex[];
  dryRun: boolean;
}

export async function attest(options: AttestOptions): Promise<AttestReport> {
  const {
    chain,
    scoresPath,
    hookBook,
    rpcUrl,
    batchSize = DEFAULT_BATCH_SIZE,
    dryRun = false,
  } = options;
  const log = options.log ?? ((m: string) => console.log(m));

  const doc = loadScores(scoresPath);
  const rows = publishable(doc, chain);
  const hash = snapshotHash(doc);
  const batches = chunk(rows, batchSize);

  log(`  ${chain}: ${doc.hooks.length} hooks in document, ${rows.length} publishable`);
  log(`  snapshot ${hash}`);
  log(`  ${batches.length} batch(es) of up to ${batchSize}`);

  if (rows.length === 0) {
    // Not an error: before Phase 3 produces behavioural evidence this is the expected
    // state, and writing zeros would be worse than writing nothing.
    log('  nothing scored yet — nothing to publish');
    return { chain, total: doc.hooks.length, publishable: 0, batches: 0, txHashes: [], dryRun };
  }

  if (dryRun) {
    log('  dry run: not sending');
    return {
      chain,
      total: doc.hooks.length,
      publishable: rows.length,
      batches: batches.length,
      txHashes: [],
      dryRun: true,
    };
  }

  if (!options.privateKey) throw new AttestorError('ATTESTOR_PK is required unless --dry-run');

  const account = privateKeyToAccount(options.privateKey);
  const transport = http(rpcUrl);
  const publicClient = createPublicClient({ transport });
  const wallet = createWalletClient({ account, transport });

  const authorised = await publicClient.readContract({
    address: hookBook,
    abi: hookBookAbi,
    functionName: 'isAttestor',
    args: [account.address],
  });
  if (!authorised) {
    throw new AttestorError(`${account.address} is not an authorised attestor on ${hookBook}`);
  }

  const txHashes: Hex[] = [];
  for (const [i, batch] of batches.entries()) {
    const asOfBlock = BigInt(Math.max(...batch.map((r) => r.as_of_block)));
    const txHash = await wallet.writeContract({
      address: hookBook,
      abi: hookBookAbi,
      functionName: 'setScores',
      args: [
        batch.map((r) => r.address),
        batch.map((r) => r.score as number),
        batch.map((r) => r.flags_bitmap),
        asOfBlock,
        hash,
      ],
      chain: null,
    });
    txHashes.push(txHash);
    log(`  batch ${i + 1}/${batches.length}: ${batch.length} hooks -> ${txHash}`);
    await publicClient.waitForTransactionReceipt({ hash: txHash });
  }

  return {
    chain,
    total: doc.hooks.length,
    publishable: rows.length,
    batches: batches.length,
    txHashes,
    dryRun: false,
  };
}
