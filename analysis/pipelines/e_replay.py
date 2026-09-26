"""Pipeline E — what Sworn would have protected.

Every other pipeline measures what hooks did. This one measures what the router is worth:
for each measured fill, find the other pools that could have filled the same trade, quote
them against the same pre-fill state, and ask whether `SwornRouter` — which probes every
candidate inside the transaction and takes the best — would have delivered more.

    protection = best_candidate_output - realized_output      (when positive)

`realized_output` is the traced `PoolManager.swap` return value, not the `Swap` event: the
event is emitted before `afterSwap` and so omits whatever the hook took there, which would
inflate every protection figure on exactly the hooks that matter. See `lib/swapcalls.py`.

Three rules keep the number from flattering itself:

* **Gas is subtracted, per fill, at the price that fill actually paid.** Probe overhead
  comes from `docs/GAS.md` (measured, not estimated: 92,717 gas for the first candidate
  and ~68,000 for each one after), multiplied by the receipt's effective gas price.
* **Candidates are quoted with empty `hookData`**, because no router ever called them and
  there is nothing to recover. A candidate hook that prices on `hookData` is therefore
  quoted on its default path.
* **Unpriceable outputs are not priced.** Protection in bps needs no prices and is the
  headline; USD is reported only for the share that `lib/pricing.py` can value from the
  chain, and that share is published as `price_confidence`.

    python -m sworn_analysis.pipelines.e_replay --chain base --n 2000
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..lib.cheap_quote import quote_many
from ..lib.compact import load_shards, parquet_safe
from ..lib.config import load_config, path_for, repo_root
from ..lib.deployments import pool_manager
from ..lib.pricing import WETH, price
from ..lib.requote import RequoteInput, result_key
from ..lib.rpc import RpcClient
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_dir, snapshot_ref
from .b_divergence import (
    archive_url,
    confirmed_sample,
    eligible_fills,
    load_confirmed,
    sample_uniform,
)

# From docs/GAS.md, measured by `SwornGasTest` against a slippage-only router.
PROBE_GAS_FIRST = 92_717
PROBE_GAS_EACH = 68_000

USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def probe_gas(candidates: int) -> int:
    """Overhead of probing `candidates` pools, in gas. Linear after the first."""
    return 0 if candidates <= 0 else PROBE_GAS_FIRST + PROBE_GAS_EACH * (candidates - 1)


def candidate_pools(
    chain: str, wanted: set[tuple[str, str]], max_per_pair: int
) -> dict[tuple[str, str], pd.DataFrame]:
    """Candidate venues for each pair in `wanted`, from the census.

    Hookless *and* hooked pools are candidates: `SwornRouter` does not refuse to route
    through a hook, it refuses to route through one that quotes differently than it
    executes. Excluding hooked candidates would understate the router by pretending the
    only safe venue is a plain pool.

    Restricted to the pairs actually sampled, and filtered **inside** the shard loop. The
    Base census is 15M pools across millions of distinct pairs; grouping all of it would
    build millions of one-row frames to answer a question about a few thousand.
    """

    def keep(part: pd.DataFrame) -> pd.DataFrame:
        pairs = pd.Series(list(zip(part.currency0, part.currency1, strict=True)), index=part.index)
        return part[pairs.isin(wanted)]

    pools = load_shards(
        snapshot_dir(f"census-{chain}"),
        columns=["pool_id", "currency0", "currency1", "fee", "tick_spacing", "hook", "hookless"],
        where=keep,
    )
    if pools.empty:
        raise SystemExit(f"no census pools for the sampled pairs on {chain}")

    # A pair with thousands of pools is a long tail of dust; probing all of them is not
    # what the router does. Keep the ones most likely to be real venues: hookless first,
    # then by fee tier, capped.
    pools = pools.sort_values(["hookless", "fee"], ascending=[False, True])
    return {key: g.head(max_per_pair) for key, g in pools.groupby(["currency0", "currency1"])}


def eth_usd_at(chain: str, blocks: list[int]) -> dict[int, float]:
    """ETH/USD at each block, from the deepest hookless WETH/USDC pool on that chain."""
    weth, usdc = WETH.get(chain), USDC_BASE
    if chain != "base" or not weth:
        return {}

    c0, c1 = sorted([weth, usdc], key=lambda a: int(a, 16))
    one_eth = 10**18
    pairs = [
        (
            RequoteInput(
                tx_hash=f"0x{b:064x}",
                log_index=0,
                currency0=c0,
                currency1=c1,
                fee=500,
                tick_spacing=10,
                hooks="0x0000000000000000000000000000000000000000",
                zero_for_one=(c0.lower() == weth),
                amount_specified=one_eth,
            ),
            b,
        )
        for b in sorted(set(blocks))
    ]
    out: dict[int, float] = {}
    for r, (_, b) in zip(
        quote_many(archive_url(chain), pool_manager(chain), pairs), pairs, strict=True
    ):
        if r.ok and r.expected > 0:
            out[b] = r.expected / 1e6
    return out


def effective_gas_prices(chain: str, tx_hashes: list[str], *, workers: int = 8) -> dict[str, int]:
    """Per-fill gas price, so overhead is charged at what that trade actually paid.

    Concurrent because this is one round trip per transaction and a ten-thousand-fill
    sample makes it the slowest step in the pipeline by an order of magnitude — longer
    than quoting every candidate route.
    """
    from concurrent.futures import ThreadPoolExecutor

    url = archive_url(chain)
    unique = list(dict.fromkeys(tx_hashes))

    def one(tx: str) -> tuple[str, int | None]:
        try:
            with RpcClient(url, timeout=60) as rpc:
                receipt = rpc.call("eth_getTransactionReceipt", [tx])
        except Exception:  # noqa: BLE001 - a missing receipt only drops gas pricing
            return tx, None
        if receipt and receipt.get("effectiveGasPrice"):
            return tx, int(receipt["effectiveGasPrice"], 16)
        return tx, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return {tx: price for tx, price in pool.map(one, unique) if price is not None}


def replay(chain: str, sample: pd.DataFrame, by_pair: dict[Any, pd.DataFrame]) -> pd.DataFrame:
    """Quote every candidate for every fill and compute protection."""
    inputs: list[tuple[RequoteInput, int]] = []
    owners: list[tuple[int, str]] = []  # (row position, candidate pool id)

    for pos, (_, r) in enumerate(sample.iterrows()):
        pool_candidates = by_pair.get((r.currency0, r.currency1))
        if pool_candidates is None:
            continue
        for _, c in pool_candidates.iterrows():
            if c.pool_id == r.pool_id:
                continue
            inputs.append(
                (
                    RequoteInput(
                        # The key must stay unique per candidate, so the pool id rides in
                        # the log index slot; nothing downstream reads it as a log index.
                        tx_hash=r.tx_hash,
                        log_index=len(inputs),
                        currency0=c.currency0,
                        currency1=c.currency1,
                        fee=int(c.fee),
                        tick_spacing=int(c.tick_spacing),
                        hooks=c.hook,
                        zero_for_one=True,
                        amount_specified=abs(int(r.req_amount)),
                    ),
                    int(r.block_number) - 1,
                )
            )
            owners.append((pos, c.pool_id))

    print(f"  quoting {len(inputs):,} candidate routes ...", flush=True)

    def show(done: int, total: int, rows: int) -> None:
        if done % 50 == 0 or done == total:
            print(f"    candidate quotes {done}/{total} batches, {rows:,} routes", flush=True)

    quoted = {}
    if inputs:
        for res in quote_many(archive_url(chain), pool_manager(chain), inputs, progress=show):
            if res.ok and res.expected > 0:
                quoted[result_key(res.tx_hash, res.log_index)] = res.expected

    best: dict[int, tuple[int, str]] = {}
    counts: dict[int, int] = {}
    for (fill_in, _), (pos, pool_id) in zip(inputs, owners, strict=True):
        counts[pos] = counts.get(pos, 0) + 1
        got = quoted.get(result_key(fill_in.tx_hash, fill_in.log_index))
        if got is None:
            continue
        if pos not in best or got > best[pos][0]:
            best[pos] = (got, pool_id)

    rows = []
    for pos, (_, r) in enumerate(sample.iterrows()):
        realized = int(r.realized)
        cand, pool_id = best.get(pos, (0, ""))
        rows.append(
            {
                "chain": chain,
                "hook": r.hook,
                "tx_hash": r.tx_hash,
                "block_number": int(r.block_number),
                "out_currency": r.currency1,
                # Decimal strings, not ints: see `confirm_against_traces`.
                "realized": str(realized),
                "best_candidate": str(cand),
                "best_pool": pool_id,
                "candidates": counts.get(pos, 0),
                "gas_overhead": probe_gas(counts.get(pos, 0)),
                "protection": str(max(0, cand - realized) if realized > 0 and cand > 0 else 0),
                # Float is fine for a ratio; it is never used as an amount.
                "protection_bps": (
                    (cand - realized) / realized * 10_000
                    if realized > 0 and cand > realized
                    else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize(
    chain: str, rep: pd.DataFrame, eth_usd: dict[int, float], gas_px: dict[str, int]
) -> dict[str, Any]:
    priced_usd, priced_net, priceable = [], [], 0
    for _, r in rep.iterrows():
        rate = eth_usd.get(int(r.block_number))
        p = price(chain, r.out_currency, int(r.protection), rate)
        if p.usd is None:
            continue
        priceable += 1
        gas_wei = int(r.gas_overhead) * gas_px.get(r.tx_hash, 0)
        gas_usd = (gas_wei / 1e18 * rate) if rate else 0.0
        priced_usd.append(p.usd)
        priced_net.append(p.usd - gas_usd)

    protected = rep[rep.protection_bps > 0]
    bps = [b for b in protected.protection_bps.tolist() if pd.notna(b)]
    overheads = sorted(rep[rep.candidates > 0].gas_overhead.tolist())

    totals: dict[str, Any] = {
        "fills_considered": int(len(rep)),
        "fills_protected": int(len(protected)),
        "protected_usd": round(sum(priced_net), 2) if priced_net else None,
        "price_confidence": round(priceable / len(rep), 4) if len(rep) else 0.0,
    }
    if bps:
        totals["median_protection_bps"] = round(float(statistics.median(bps)), 2)
    if overheads:
        totals["gas_overhead_p50"] = int(statistics.median(overheads))
        totals["gas_overhead_p90"] = int(overheads[max(0, int(0.9 * len(overheads)) - 1)])
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-candidates", type=int, default=4)
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")

    # Deliberately the same cache key `b_divergence` writes: replay must answer "what
    # would Sworn have done" about *the fills that were measured*, not about a fresh draw.
    # Sharing the sample also means it costs no second index scan.
    key = f"{args.chain}-uniform-{args.n}-{args.seed}"
    sample = load_confirmed(key)
    if sample is None:
        fills = eligible_fills(args.chain)
        sample = sample_uniform(fills, args.n, args.seed)
        print(f"  sampling {len(sample):,} fills from {sample.hook.nunique():,} hooks")
        del fills
        sample = confirmed_sample(args.chain, sample, cache_key=key, refresh=True)

    sample = sample[sample.confirmed].reset_index(drop=True)
    if sample.empty:
        raise SystemExit("no fills survived trace confirmation")

    wanted = set(zip(sample.currency0, sample.currency1, strict=True))
    print(f"  {len(wanted):,} distinct pairs in the sample", flush=True)
    by_pair = candidate_pools(args.chain, wanted, args.max_candidates)
    print(f"  {sum(len(v) for v in by_pair.values()):,} candidate pools found", flush=True)
    rep = replay(args.chain, sample, by_pair)

    blocks = rep.block_number.tolist()
    print("  pricing from the chain ...", flush=True)
    eth_usd = eth_usd_at(args.chain, blocks)
    gas_px = effective_gas_prices(args.chain, rep.tx_hash.tolist())

    totals = summarize(args.chain, rep, eth_usd, gas_px)

    by_hook = []
    for hook, g in rep.groupby("hook"):
        p = g[g.protection_bps > 0]
        if p.empty:
            continue
        by_hook.append(
            {
                "address": hook,
                "fills": int(len(g)),
                "fills_protected": int(len(p)),
                "median_protection_bps": round(float(p.protection_bps.median()), 2),
            }
        )
    by_hook.sort(key=lambda r: -r["median_protection_bps"])

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "e_replay",
            "snapshots": [
                snapshot_ref(f"census-{args.chain}"),
                snapshot_ref(f"fills-{args.chain}"),
            ],
        },
        "totals": totals,
        "by_chain": [{"chain": args.chain, **totals}],
        "by_hook": by_hook[:50],
    }
    validate_result("replay.json", document)

    out = path_for("results") / "replay.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    cache = path_for("results").parent / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    parquet_safe(rep).to_parquet(cache / "e_replay_fills.parquet", index=False)

    print(f"\n  fills considered  {totals['fills_considered']:,}")
    print(f"  fills protected   {totals['fills_protected']:,}")
    print(f"  median protection {totals.get('median_protection_bps', 0)} bps")
    print(f"  protected (net)   {totals['protected_usd']} USD")
    print(f"  price confidence  {totals['price_confidence']:.1%}")
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
