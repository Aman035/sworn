/**
 * sworn-attestor. Publish computed hook scores to `HookBook`.
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
  /** Batches the registry already holds at this `asOfBlock` or newer. */
  skipped: number;
}

/** `StaleUpdate(uint64,uint64)`: the registry already holds this block or newer. */
export const STALE_UPDATE_SELECTOR = '0xecef4381';

export function isStaleUpdate(error: unknown): boolean {
  // viem nests the revert data several layers down and the shape differs by transport, so
  // match on the selector anywhere in the serialized error rather than on a class.
  const text = error instanceof Error ? `${error.message}${error.stack ?? ''}` : String(error);
  return text.includes(STALE_UPDATE_SELECTOR) || text.includes('StaleUpdate');
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
    log('  nothing scored yet. Nothing to publish');
    return {
      chain,
      total: doc.hooks.length,
      publishable: 0,
      batches: 0,
      txHashes: [],
      dryRun,
      skipped: 0,
    };
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
      skipped: 0,
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
  let skipped = 0;
  for (const [i, batch] of batches.entries()) {
    const asOfBlock = BigInt(Math.max(...batch.map((r) => r.as_of_block)));
    const args = [
      batch.map((r) => r.address),
      batch.map((r) => r.score as number),
      batch.map((r) => r.flags_bitmap),
      asOfBlock,
      hash,
    ] as const;

    // `HookBook` rejects a write that is not newer than what it holds, which is replay
    // protection and staleness protection in one. This job runs hourly and the analysis
    // it publishes moves far more slowly, so *most* runs have nothing newer to say.
    // Simulating first turns the expected case into a no-op instead of an hourly page.
    try {
      await publicClient.simulateContract({
        account,
        address: hookBook,
        abi: hookBookAbi,
        functionName: 'setScores',
        args,
      });
    } catch (error) {
      if (isStaleUpdate(error)) {
        skipped += 1;
        log(`  batch ${i + 1}/${batches.length}: already current at block ${asOfBlock}`);
        continue;
      }
      throw error;
    }

    const txHash = await wallet.writeContract({
      address: hookBook,
      abi: hookBookAbi,
      functionName: 'setScores',
      args,
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
    skipped,
  };
}
