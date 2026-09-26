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
from ..lib.pricing import NATIVE, price
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

# A candidate quoting a large multiple of the executed route is far more likely a mispriced
# dust pool than free money, and counting it is the single easiest way to fabricate an ROI
# figure. In this sample the largest "protection" was 10,090,820 bps — a thousandfold — on a
# fill of 49 microtokens. Anything above this bound is counted and published separately
# rather than folded into the headline.
MAX_PLAUSIBLE_PROTECTION_BPS = 5_000.0


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


# Probe size for the reference rate. Small on purpose: 1 ETH through the shallower Base
# ETH/USDC tiers moves the price by more than 40%, so a "rate" quoted at that size is a
# measure of the pool's depth, not of the price.
ETH_PROBE_WEI = 10**16  # 0.01 ETH

# Tiers to consider for the reference pool. The deepest wins, decided by measurement.
ETH_USDC_TIERS: tuple[tuple[int, int], ...] = ((500, 10), (3000, 60), (100, 1), (10000, 200))


def _eth_usdc_input(fee: int, tick_spacing: int, tag: int, amount: int) -> RequoteInput:
    # Native ETH, not WETH: v4 pools on Base quote ETH/USDC against `address(0)`, and the
    # WETH/USDC pools are far thinner. Quoting the wrong one gave 880 USDC per ETH against
    # a true 2,660 — a price feed that is wrong by a factor of three is worse than none.
    return RequoteInput(
        tx_hash=f"0x{tag:064x}",
        log_index=0,
        currency0=NATIVE,
        currency1=USDC_BASE,
        fee=fee,
        tick_spacing=tick_spacing,
        hooks=NATIVE,
        zero_for_one=True,
        amount_specified=amount,
    )


def deepest_eth_usdc_tier(chain: str, block: int) -> tuple[int, int] | None:
    """Pick the reference tier by quoting each and taking the best rate.

    Least slippage on an identical probe is the cheapest available proxy for depth, and it
    is measured rather than assumed — the tier that is deepest on Base today is not
    guaranteed to be the one hard-coded last month.
    """
    pairs = [
        (_eth_usdc_input(fee, ts, i, ETH_PROBE_WEI), block)
        for i, (fee, ts) in enumerate(ETH_USDC_TIERS)
    ]
    results = quote_many(archive_url(chain), pool_manager(chain), pairs)
    best, best_out = None, 0
    for (fee, ts), r in zip(ETH_USDC_TIERS, results, strict=True):
        if r.ok and r.expected > best_out:
            best, best_out = (fee, ts), r.expected
    if best is None:
        return None
    print(
        f"  reference ETH/USDC pool: fee={best[0]} tickSpacing={best[1]} "
        f"({best_out / ETH_PROBE_WEI * 1e18 / 1e6:,.0f} USDC/ETH at block {block})",
        flush=True,
    )
    return best


def eth_usd_at(chain: str, blocks: list[int]) -> dict[int, float]:
    """ETH/USD at each block, from the deepest hookless ETH/USDC pool on that chain."""
    if chain != "base":
        return {}
    unique = sorted(set(blocks))
    if not unique:
        return {}

    tier = deepest_eth_usdc_tier(chain, unique[len(unique) // 2])
    if tier is None:
        return {}
    fee, tick_spacing = tier

    pairs = [(_eth_usdc_input(fee, tick_spacing, b, ETH_PROBE_WEI), b) for b in unique]

    def show(done: int, total: int, rows: int) -> None:
        if done % 50 == 0 or done == total:
            print(f"    eth/usd {done}/{total} batches, {rows:,} blocks", flush=True)

    out: dict[int, float] = {}
    for r, (_, b) in zip(
        quote_many(archive_url(chain), pool_manager(chain), pairs, progress=show),
        pairs,
        strict=True,
    ):
        if r.ok and r.expected > 0:
            # USDC has 6 decimals; scale the probe back up to one whole ETH.
            out[b] = r.expected / 1e6 * (10**18 / ETH_PROBE_WEI)
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
    plausible = rep[rep.protection_bps <= MAX_PLAUSIBLE_PROTECTION_BPS]
    implausible = int(len(rep) - len(plausible))

    gross, gas_costs, priceable = [], [], 0
    for _, r in plausible.iterrows():
        rate = eth_usd.get(int(r.block_number))
        p = price(chain, r.out_currency, int(r.protection), rate)
        if p.usd is None:
            # Protection denominated in a token nothing can value is not protection you
            # can spend. It still counts in the bps median; it never reaches the dollars.
            continue
        priceable += 1
        gas_wei = int(r.gas_overhead) * gas_px.get(r.tx_hash, 0)
        gross.append(p.usd)
        gas_costs.append((gas_wei / 1e18 * rate) if rate else 0.0)

    protected = plausible[plausible.protection_bps > 0]
    bps = [b for b in protected.protection_bps.tolist() if pd.notna(b)]
    probed = plausible[plausible.candidates > 0]
    overheads = sorted(probed.gas_overhead.tolist())

    totals: dict[str, Any] = {
        "fills_considered": int(len(rep)),
        # Fills where at least one alternative venue existed at all. The rest are pairs
        # with a single pool, where there is nothing for a router to choose between.
        "fills_with_alternatives": int(len(probed)),
        "fills_protected": int(len(protected)),
        "implausible_fills": implausible,
        "max_plausible_protection_bps": MAX_PLAUSIBLE_PROTECTION_BPS,
        "protected_usd_gross": round(sum(gross), 2) if gross else None,
        "probe_gas_usd": round(sum(gas_costs), 2) if gas_costs else None,
        "protected_usd": round(sum(gross) - sum(gas_costs), 2) if gross else None,
        "price_confidence": round(priceable / len(rep), 4) if len(rep) else 0.0,
    }
    if bps:
        totals["median_protection_bps"] = round(float(statistics.median(bps)), 2)

    # The dollar sums are real but they are not representative: in this sample ten
    # transactions paying an unusually high priority fee contributed 92% of the gas total.
    # The median is what a trade actually costs to protect, and the concentration figure is
    # published so nobody has to rediscover why the two disagree.
    paid = sorted((g for g in gas_costs if g > 0), reverse=True)
    if paid:
        totals["probe_gas_usd_median"] = round(float(statistics.median(paid)), 6)
        totals["gas_cost_top10_share"] = round(sum(paid[:10]) / sum(paid), 4)

    if overheads:
        totals["gas_overhead_p50"] = int(statistics.median(overheads))
        totals["gas_overhead_p90"] = int(overheads[max(0, int(0.9 * len(overheads)) - 1)])

    # The number an integrator actually needs: probing costs a fixed amount of gas and
    # saves a proportion of the trade, so it pays above some notional and not below it.
    if gas_costs and bps:
        median_gas = float(statistics.median(paid)) if paid else 0.0
        hit_rate = len(protected) / max(1, len(probed))
        expected_bps = statistics.median(bps) * hit_rate
        if median_gas > 0 and expected_bps > 0:
            totals["breakeven_notional_usd"] = round(median_gas / (expected_bps / 10_000), 2)
            totals["protection_hit_rate"] = round(hit_rate, 4)
    return totals


def cache_dir() -> Any:
    d = path_for("results").parent / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_side_data() -> tuple[dict[int, float], dict[str, int]] | None:
    """ETH/USD per block and gas price per transaction, from a previous run.

    Both are thousands of RPC round trips and neither changes for a fixed sample, so
    caching them is what makes re-summarising under a different plausibility bound cost
    seconds instead of a quarter of an hour.
    """
    path = cache_dir() / "e_replay_prices.json"
    if not path.is_file():
        return None
    blob = json.loads(path.read_text(encoding="utf-8"))
    print(f"  reusing cached prices for {len(blob['eth_usd']):,} blocks", flush=True)
    return {int(k): float(v) for k, v in blob["eth_usd"].items()}, {
        k: int(v) for k, v in blob["gas_price"].items()
    }


def save_side_data(eth_usd: dict[int, float], gas_px: dict[str, int]) -> None:
    (cache_dir() / "e_replay_prices.json").write_text(
        json.dumps({"eth_usd": {str(k): v for k, v in eth_usd.items()}, "gas_price": gas_px}),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument(
        "--resummarize",
        action="store_true",
        help="rebuild the document from cached per-fill routes and prices, without quoting",
    )
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

    cached_prices = load_side_data() if args.resummarize else None
    if args.resummarize and cached_prices is not None:
        rep = pd.read_parquet(cache_dir() / "e_replay_fills.parquet")
        print(f"  re-summarising {len(rep):,} cached routes", flush=True)
        eth_usd, gas_px = cached_prices
    else:
        wanted = set(zip(sample.currency0, sample.currency1, strict=True))
        print(f"  {len(wanted):,} distinct pairs in the sample", flush=True)
        by_pair = candidate_pools(args.chain, wanted, args.max_candidates)
        print(f"  {sum(len(v) for v in by_pair.values()):,} candidate pools found", flush=True)
        rep = replay(args.chain, sample, by_pair)

        print("  pricing from the chain ...", flush=True)
        eth_usd = eth_usd_at(args.chain, rep.block_number.tolist())
        gas_px = effective_gas_prices(args.chain, rep.tx_hash.tolist())
        save_side_data(eth_usd, gas_px)

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

    parquet_safe(rep).to_parquet(cache_dir() / "e_replay_fills.parquet", index=False)

    print(f"\n  fills considered   {totals['fills_considered']:,}")
    print(f"  with alternatives  {totals['fills_with_alternatives']:,}")
    print(f"  fills protected    {totals['fills_protected']:,}")
    print(f"  implausible (cut)  {totals['implausible_fills']:,}")
    print(f"  median protection  {totals.get('median_protection_bps', 0)} bps")
    print(f"  protected gross    {totals['protected_usd_gross']} USD")
    print(
        f"  probe gas          {totals['probe_gas_usd']} USD total, "
        f"{totals.get('probe_gas_usd_median', 0):.4f} median "
        f"({totals.get('gas_cost_top10_share', 0):.0%} of it from 10 fills)"
    )
    print(f"  protected net      {totals['protected_usd']} USD")
    if "breakeven_notional_usd" in totals:
        print(f"  breakeven notional {totals['breakeven_notional_usd']:,.2f} USD")
    print(f"  price confidence   {totals['price_confidence']:.1%}")
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
