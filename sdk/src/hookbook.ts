import { hookBookAbi } from './abi.js';
import { HOOK_FLAGS, type Address, type HookFlagName } from './types.js';

/**
 * Any viem-compatible public client.
 *
 * Typed loosely on purpose. viem declares `readContract` with a generic constrained to
 * the ABI and the function name, so a narrow structural interface cannot be satisfied by
 * a real `PublicClient` — the `functionName: string` widens and the call fails to
 * typecheck at the consumer, which is exactly backwards.
 *
 * The looseness is contained: this package owns the ABI, the function names and the
 * decoding, and every value read here is validated before use.
 */
export interface ReadClient {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  readContract: (args: any) => Promise<any>;
}

export interface HookScore {
  hook: Address;
  score: number;
  flags: number;
  /** False when the hook has never been measured — which is *not* the same as clean. */
  scored: boolean;
  ageSeconds: bigint;
}

export interface HookBookReaderOptions {
  /** How long a cached read stays valid. Scores move on the attestor's cadence, not per block. */
  cacheTtlMs?: number;
  /** Reads older than this are treated as unusable rather than merely old. */
  maxAgeSeconds?: bigint;
}

const DEFAULT_CACHE_TTL_MS = 60_000;

/** Turn a flags word into the names that are set, in bit order. */
export function explainFlags(flags: number): HookFlagName[] {
  return (Object.keys(HOOK_FLAGS) as HookFlagName[]).filter(
    (name) => (flags & HOOK_FLAGS[name]) !== 0,
  );
}

/** A one-line, human-readable verdict for a hook. */
export function explain(result: HookScore): string {
  if (!result.scored) {
    return 'never measured — absence of a score is not evidence of honesty';
  }
  const names = explainFlags(result.flags).filter((n) => n !== 'INSUFFICIENT_DATA');
  const suffix = names.length > 0 ? ` (${names.join(', ')})` : '';
  return `score ${result.score}/100${suffix}`;
}

export class HookBookReader {
  private readonly cache = new Map<string, { at: number; value: HookScore }>();
  private readonly ttl: number;
  private readonly maxAgeSeconds: bigint | undefined;

  constructor(
    private readonly client: ReadClient,
    private readonly address: Address,
    options: HookBookReaderOptions = {},
  ) {
    this.ttl = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
    this.maxAgeSeconds = options.maxAgeSeconds;
  }

  async get(hook: Address): Promise<HookScore> {
    const key = hook.toLowerCase();
    const hit = this.cache.get(key);
    if (hit && Date.now() - hit.at < this.ttl) return hit.value;

    const [score, ageSeconds, scored] = (await this.client.readContract({
      address: this.address,
      abi: hookBookAbi,
      functionName: 'scoreWithAge',
      args: [hook],
    })) as [number, bigint, boolean];

    const flags = (await this.client.readContract({
      address: this.address,
      abi: hookBookAbi,
      functionName: 'flags',
      args: [hook],
    })) as number;

    const value: HookScore = {
      hook,
      score: Number(score),
      flags: Number(flags),
      scored,
      ageSeconds,
    };
    this.cache.set(key, { at: Date.now(), value });
    return value;
  }

  /**
   * Whether a hook is acceptable under a score ceiling.
   *
   * Unscored hooks are rejected when a ceiling is set: the caller asked for evidence, and
   * there is none. A stale score is likewise treated as no score rather than as the last
   * known good value — that is the failure mode an attacker would aim for.
   */
  async isAcceptable(hook: Address, maxScore: number): Promise<{ ok: boolean; reason: string }> {
    const result = await this.get(hook);
    if (!result.scored) return { ok: false, reason: 'no score published for this hook' };
    if (this.maxAgeSeconds !== undefined && result.ageSeconds > this.maxAgeSeconds) {
      return { ok: false, reason: `score is ${result.ageSeconds}s old, older than the limit` };
    }
    if (result.score > maxScore) {
      return { ok: false, reason: `score ${result.score} exceeds the ceiling of ${maxScore}` };
    }
    return { ok: true, reason: explain(result) };
  }

  clearCache(): void {
    this.cache.clear();
  }
}
