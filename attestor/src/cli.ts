#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { resolve } from 'node:path';

import { attest } from './index.js';
import type { Address, Hex } from 'viem';

function env(name: string): string | undefined {
  const v = process.env[name];
  return v && v.length > 0 ? v : undefined;
}

async function main(): Promise<number> {
  const { values } = parseArgs({
    options: {
      chain: { type: 'string', default: 'base' },
      scores: { type: 'string' },
      'hook-book': { type: 'string' },
      // The chain whose *data* is being published is not always the chain the registry
      // lives on: Base-derived scores are written to a Base Sepolia HookBook while the
      // mainnet registry is unfunded. Keeping the two separate stops `--chain` from
      // silently pointing the writer at the wrong network.
      'rpc-url': { type: 'string' },
      'batch-size': { type: 'string' },
      'dry-run': { type: 'boolean', default: false },
    },
  });

  const chain = values.chain as string;
  const scoresPath = resolve(values.scores ?? 'data/results/scores.json');
  const dryRun = values['dry-run'] as boolean;

  const rpcUrl =
    (values['rpc-url'] as string | undefined) ??
    env(`${chain.toUpperCase()}_RPC_ARCHIVE`) ??
    env('BASE_SEPOLIA_RPC');
  const hookBook = (values['hook-book'] ?? env(`HOOKBOOK_ADDRESS_${chain.toUpperCase()}`)) as
    | Address
    | undefined;

  if (!dryRun && !hookBook) {
    console.error(
      `no HookBook address for ${chain}: pass --hook-book or set HOOKBOOK_ADDRESS_${chain.toUpperCase()}`,
    );
    return 2;
  }
  if (!dryRun && !rpcUrl) {
    console.error(`no RPC for ${chain}`);
    return 2;
  }

  const report = await attest({
    chain,
    scoresPath,
    hookBook: (hookBook ?? '0x0000000000000000000000000000000000000000') as Address,
    rpcUrl: rpcUrl ?? '',
    ...(env('ATTESTOR_PK') ? { privateKey: env('ATTESTOR_PK') as Hex } : {}),
    ...(values['batch-size'] ? { batchSize: Number(values['batch-size']) } : {}),
    dryRun,
  });

  const written = report.batches - report.skipped;
  console.log(
    `\n${report.chain}: ${report.publishable}/${report.total} scored, ` +
      `${written}/${report.batches} batch(es) written` +
      (report.skipped ? `, ${report.skipped} already current` : '') +
      (report.dryRun ? ' (dry run)' : ''),
  );
  return 0;
}

main().then(
  (code) => process.exit(code),
  (err) => {
    console.error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  },
);
