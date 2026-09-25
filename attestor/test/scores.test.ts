import { describe, expect, it } from 'vitest';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { AttestorError, chunk, loadScores, publishable, snapshotHash } from '../src/scores.js';
import type { ScoresDocument } from '../src/scores.js';

function doc(overrides: Partial<ScoresDocument> = {}): ScoresDocument {
  return {
    meta: {
      generated_at: '2026-09-26T00:00:00Z',
      script_commit: 'abc1234',
      config_version: 1,
      snapshots: [{ name: 'census-base', sha256: 'a'.repeat(64), block_to: 51_778_292 }],
    },
    weights: { charged_rate: 0.3 },
    hooks: [],
    ...overrides,
  };
}

function row(over: Partial<ScoresDocument['hooks'][number]> = {}) {
  return {
    chain: 'base',
    address: `0x${'11'.repeat(20)}` as `0x${string}`,
    score: 42,
    flags_bitmap: 3,
    flags: ['DIVERGENT', 'ENV_SENSITIVE'],
    as_of_block: 51_778_292,
    insufficient_data: false,
    proof: { snapshot_sha256: 'a'.repeat(64) },
    ...over,
  };
}

function write(d: ScoresDocument): string {
  const dir = mkdtempSync(join(tmpdir(), 'sworn-'));
  const path = join(dir, 'scores.json');
  writeFileSync(path, JSON.stringify(d));
  return path;
}

describe('loadScores', () => {
  it('loads a well-formed document', () => {
    const loaded = loadScores(write(doc({ hooks: [row()] })));
    expect(loaded.hooks).toHaveLength(1);
  });

  it('refuses a document with no snapshot provenance', () => {
    // A score that cannot be re-derived is an opinion, and opinions do not belong
    // on-chain under a snapshot hash.
    const bad = doc();
    bad.meta.snapshots = [];
    expect(() => loadScores(write(bad))).toThrow(AttestorError);
  });
});

describe('publishable', () => {
  it('skips unscored hooks rather than writing them as zero', () => {
    const rows = publishable(
      doc({ hooks: [row(), row({ score: null, insufficient_data: true })] }),
      'base',
    );
    // Writing 0 would make "unmeasured" indistinguishable from "measured clean".
    expect(rows).toHaveLength(1);
    expect(rows[0]!.score).toBe(42);
  });

  it('skips hooks flagged insufficient even if a score slipped through', () => {
    expect(publishable(doc({ hooks: [row({ insufficient_data: true })] }), 'base')).toHaveLength(0);
  });

  it('skips rows with no as-of block', () => {
    expect(publishable(doc({ hooks: [row({ as_of_block: 0 })] }), 'base')).toHaveLength(0);
  });

  it('filters by chain', () => {
    const rows = publishable(doc({ hooks: [row(), row({ chain: 'bnb' })] }), 'base');
    expect(rows).toHaveLength(1);
  });

  it('returns nothing when the whole document is unmeasured', () => {
    // The expected state before Phase 3 lands: publishing nothing is correct.
    const all = Array.from({ length: 5 }, () => row({ score: null, insufficient_data: true }));
    expect(publishable(doc({ hooks: all }), 'base')).toHaveLength(0);
  });
});

describe('snapshotHash', () => {
  it('returns the primary snapshot hash as bytes32', () => {
    expect(snapshotHash(doc())).toBe(`0x${'a'.repeat(64)}`);
  });

  it('throws when there is no hash to publish', () => {
    const bad = doc();
    bad.meta.snapshots = [{ name: 'x', sha256: '' }];
    expect(() => snapshotHash(bad)).toThrow(AttestorError);
  });
});

describe('chunk', () => {
  it('splits evenly and keeps every row', () => {
    const rows = Array.from({ length: 250 }, (_, i) => i);
    const batches = chunk(rows, 100);
    expect(batches.map((b) => b.length)).toEqual([100, 100, 50]);
    expect(batches.flat()).toEqual(rows);
  });

  it('rejects a non-positive size', () => {
    expect(() => chunk([1], 0)).toThrow(AttestorError);
  });

  it('handles an empty list', () => {
    expect(chunk([], 10)).toEqual([]);
  });
});
