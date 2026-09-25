import { readFileSync } from 'node:fs';

/** One hook's score as `data/results/scores.json` carries it. */
export interface ScoreRow {
  chain: string;
  address: `0x${string}`;
  /** null means the hook has too little evidence to score — not that it is clean. */
  score: number | null;
  flags_bitmap: number;
  flags: string[];
  as_of_block: number;
  insufficient_data: boolean;
  proof: { snapshot_sha256: string };
}

export interface ScoresDocument {
  meta: {
    generated_at: string;
    script_commit: string;
    config_version: number;
    snapshots: { name: string; sha256: string; block_to?: number }[];
  };
  weights: Record<string, number>;
  hooks: ScoreRow[];
}

export class AttestorError extends Error {}

export function loadScores(path: string): ScoresDocument {
  const doc = JSON.parse(readFileSync(path, 'utf8')) as ScoresDocument;

  if (!doc.meta?.snapshots?.length) {
    // A score without provenance cannot be re-derived, which is the only thing that makes
    // it worth more than an opinion.
    throw new AttestorError(`${path}: no meta.snapshots — refusing to attest unprovenanced scores`);
  }
  if (!Array.isArray(doc.hooks)) {
    throw new AttestorError(`${path}: no hooks array`);
  }
  return doc;
}

/**
 * The rows that are actually publishable.
 *
 * Unscored hooks are skipped rather than written as 0. Writing them would make
 * "unmeasured" indistinguishable from "measured clean" on-chain — the exact confusion
 * `HookBook` exists to avoid — and would burn gas saying nothing.
 */
export function publishable(doc: ScoresDocument, chain: string): ScoreRow[] {
  return doc.hooks.filter(
    (h) => h.chain === chain && h.score !== null && !h.insufficient_data && h.as_of_block > 0,
  );
}

export function snapshotHash(doc: ScoresDocument): `0x${string}` {
  const primary = doc.meta.snapshots[0];
  if (!primary?.sha256) throw new AttestorError('scores document has no primary snapshot hash');
  return `0x${primary.sha256}` as `0x${string}`;
}

/** Split into batches small enough to fit a block's gas limit comfortably. */
export function chunk<T>(rows: T[], size: number): T[][] {
  if (size <= 0) throw new AttestorError('batch size must be positive');
  const out: T[][] = [];
  for (let i = 0; i < rows.length; i += size) out.push(rows.slice(i, i + size));
  return out;
}
