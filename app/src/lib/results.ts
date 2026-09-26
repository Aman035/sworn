import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Load the committed result files.
 *
 * Read at build time, not fetched at runtime. The dashboard shows a *pinned snapshot*:
 * every figure traces to a `meta.snapshots[]` entry with a sha256, so a reader can
 * re-derive it. A live query would be prettier and unreproducible.
 */
const RESULTS = join(process.cwd(), '..', 'data', 'results');

export interface Snapshot {
  name: string;
  sha256: string;
  chain?: string;
  block_from?: number;
  block_to?: number;
  rows?: number;
}

export interface Meta {
  generated_at: string;
  script_commit: string;
  config_version: number;
  pipeline?: string;
  snapshots: Snapshot[];
}

export interface CensusChain {
  chain: string;
  hooks_total: number;
  pools_total: number;
  hooked_pools: number;
  block_from: number;
  block_to: number;
  with_returns_delta?: number;
  dynamic_fee_pools?: number;
  upgradeable?: number;
  verified?: number;
  allowlisted?: number;
  metadata_hooks_covered?: number;
  by_flag_combination?: { flags_bitmap: number; hooks: number; names?: string[] }[];
}

export interface TopHook {
  chain: string;
  address: string;
  pool_count: number;
  flags_bitmap?: number;
  returns_delta?: boolean;
  dynamic_fee?: boolean;
  upgradeable?: boolean;
  verified?: boolean;
  allowlisted?: boolean;
  first_seen_block?: number;
}

export interface DivergenceHook {
  chain: string;
  address: string;
  fills: number;
  charged_fills: number;
  charged_rate: number;
  divergent: boolean;
  dynamic_fee?: boolean;
  median_take_bps?: number;
  median_charged_excess_bps?: number;
  hook_data_unknown_share?: number;
  /** Fills that came out better than quoted: impossible, so a false-positive estimate. */
  overdelivered_fills?: number;
  net_charged_fills?: number;
  net_charged_rate?: number;
  beats_noise_floor?: boolean;
}

export interface ScoreRow {
  chain: string;
  address: string;
  score: number | null;
  flags: string[];
  insufficient_data?: boolean;
}

export interface ProbeHook {
  chain: string;
  address: string;
  env_sensitive: boolean;
  max_disagreement_bps?: number;
  signals?: string[];
  static: { env_opcodes_present?: string[] };
  trace?: { env_opcodes_on_swap_path?: string[]; available?: boolean };
}

export interface Product {
  product: string;
  chain: string;
  router?: string;
  fills_total?: number;
  fills_into_divergent: number;
  share_of_product_v4_volume?: number;
  confidence: number;
  sources?: string[];
}

function load<T>(file: string): T | null {
  try {
    return JSON.parse(readFileSync(join(RESULTS, file), 'utf8')) as T;
  } catch {
    // A missing result file means that pipeline has not run. The page says so rather
    // than rendering zeros, which would read as a measurement.
    return null;
  }
}

export const census = () =>
  load<{ meta: Meta; chains: CensusChain[]; top_hooks: TopHook[] }>('census.json');
export const divergence = () =>
  load<{
    meta: Meta;
    totals: Record<string, number>;
    hooks: DivergenceHook[];
    sensitivity: unknown[];
  }>('divergence.json');
export const probe = () => load<{ meta: Meta; hooks: ProbeHook[] }>('probe.json');
export const attribution = () =>
  load<{ meta: Meta; unlabeled_share: number; products: Product[] }>('attribution.json');
export const replay = () =>
  load<{
    meta: Meta;
    totals: {
      fills_considered: number;
      fills_with_alternatives?: number;
      fills_protected: number;
      implausible_fills?: number;
      median_protection_bps?: number;
      probe_gas_usd_median?: number;
      breakeven_notional_usd?: number;
      protection_hit_rate?: number;
      price_confidence?: number;
    };
  }>('replay.json');

export const caught = () =>
  load<{
    meta: Meta;
    where: { chain: string; block: number; hook: string };
    observed: {
      caller_a_out: number;
      caller_b_out: number;
      charged_extra_bps: number;
      sworn_settled_out: number;
      recovered_bps: number;
    };
  }>('caught.json');

export const scores = () => load<{ meta: Meta; hooks: ScoreRow[] }>('scores.json');

export const precision = () =>
  load<{ meta: Meta; ground_truth: string; methods: Record<string, number | string>[] }>(
    'precision.json',
  );

export const DISTINGUISHING = [
  'GASPRICE',
  'ORIGIN',
  'COINBASE',
  'PREVRANDAO',
  'BASEFEE',
  'GASLIMIT',
];

// A missing measurement says so. Rendering it as a blank or a zero would make an
// unmeasured hook look clean, which is the one mistake this whole site exists to avoid.
export function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return 'n/a';
  return n.toLocaleString('en-US');
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return 'n/a';
  return `${(n * 100).toFixed(digits)}%`;
}

export function short(addr: string): string {
  return `${addr.slice(0, 10)}…${addr.slice(-6)}`;
}
