"""Pipeline B — settled-trade divergence.

For every sampled fill in a hooked pool: re-quote the identical swap against the state
immediately before it, compare with what was actually delivered, and attribute the
difference to the hook. Aggregate per hook into `data/results/divergence.json`.

`docs/METRICS.md` defines every term. Two population rules are enforced here because they
make the comparison well-posed rather than merely convenient:

* a fill is identified by `(txHash, logIndex)` — a Base transaction can carry 126 `Swap`
  events and 37.8% of fills share one;
* only fills that are the sole fill for their pool in their transaction are measured,
  because `vm.rollFork(txHash)` rolls to before the *whole* transaction and a second fill
  in the same pool would be quoted against a state that never existed for it.

Sampling is by hook, not uniform: a hook with a million fills does not need a million
re-quotes to establish its charged rate, and a hook with twenty needs all of them.

    python -m sworn_analysis.pipelines.b_divergence --chain base --per-hook 8 --max-hooks 40
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..lib.compact import SWAP_SHARD_PREFIX, load_shards
from ..lib.config import load_config, path_for, repo_root
from ..lib.requote import RequoteInput, excess_take_bps, result_key, run_batch
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_dir, snapshot_ref


def eligible_fills(chain: str) -> pd.DataFrame:
    """Hooked, exact-input fills that are the only fill for their pool in their tx."""
    hooked = load_shards(
        snapshot_dir(f"census-{chain}"),
        columns=[
            "pool_id",
            "currency0",
            "currency1",
            "fee",
            "tick_spacing",
            "hook",
            "hookless",
            "dynamic_fee",
        ],
        where=lambda part: part[~part.hookless],
    )
    if hooked.empty:
        raise SystemExit(f"no census for {chain}")
    wanted = set(hooked.pool_id)

    fills = load_shards(
        snapshot_dir(f"fills-{chain}"),
        SWAP_SHARD_PREFIX,
        columns=[
            "pool_id",
            "sender",
            "amount0",
            "amount1",
            "tx_hash",
            "log_index",
            "fee",
            "block_number",
        ],
        where=lambda part: part[part.pool_id.isin(wanted)],
    )
    if fills.empty:
        raise SystemExit(f"no fills for {chain}")

    m = fills.merge(
        hooked.drop(columns=["hookless"]), on="pool_id", how="inner", suffixes=("_fill", "_pool")
    )
    del fills, hooked

    m["a0"] = m.amount0.map(int)
    m["a1"] = m.amount1.map(int)

    counts = m.groupby(["tx_hash", "pool_id"]).size().rename("n")
    m = m.join(counts, on=["tx_hash", "pool_id"])
    m = m[m.n == 1]

    # Exact-input, token0 in. Restricting the direction keeps the re-quote a single
    # well-defined call; the opposite direction is a straightforward extension.
    return m[(m.a0 < 0) & (m.a1 > 0)]


def sample_by_hook(fills: pd.DataFrame, per_hook: int, max_hooks: int, seed: int) -> pd.DataFrame:
    """Take up to `per_hook` fills from each of the busiest `max_hooks` hooks."""
    busiest = fills.groupby("hook").size().sort_values(ascending=False).head(max_hooks).index
    subset = fills[fills.hook.isin(set(busiest))]

    # Sample per hook by index rather than via `groupby.apply`: the latter is deprecated
    # for operating on the grouping column, and the warning would otherwise appear in
    # every pipeline log.
    picks = []
    for _, group in subset.groupby("hook", sort=False):
        picks.append(group.sample(n=min(per_hook, len(group)), random_state=seed))
    return pd.concat(picks, ignore_index=True) if picks else subset.head(0)


def measure(chain: str, sample: pd.DataFrame) -> pd.DataFrame:
    inputs = [
        RequoteInput(
            tx_hash=r.tx_hash,
            log_index=int(r.log_index),
            currency0=r.currency0,
            currency1=r.currency1,
            fee=int(r.fee_pool),
            tick_spacing=int(r.tick_spacing),
            hooks=r.hook,
            zero_for_one=True,
            amount_specified=abs(r.a0),
        )
        for _, r in sample.iterrows()
    ]
    print(f"  re-quoting {len(inputs)} hooked fills ...", flush=True)
    results = run_batch(chain, inputs, name=f"divergence-{chain}", timeout=7200)
    by_key = {result_key(r.tx_hash, r.log_index): r for r in results}

    rows = []
    for _, r in sample.iterrows():
        q = by_key.get(result_key(r.tx_hash, int(r.log_index)))
        if q is None or not q.ok or q.expected <= 0:
            rows.append(
                {
                    "chain": chain,
                    "hook": r.hook,
                    "block_time": int(r.block_number),
                    "usable": False,
                    "excess_bps": None,
                    "take_bps": None,
                }
            )
            continue
        # `fee_fill` is the fee actually applied to this swap, which for a dynamic-fee
        # pool is the hook's choice at that moment rather than a property of the key.
        nominal_pips = int(r.fee_fill) if bool(r.dynamic_fee) else int(r.fee_pool)
        shortfall = (q.expected - r.a1) / q.expected
        rows.append(
            {
                "chain": chain,
                "hook": r.hook,
                "block_time": int(r.block_number),
                "usable": True,
                "take_bps": shortfall * 10_000,
                "excess_bps": excess_take_bps(q.expected, r.a1, nominal_pips),
                "nominal_bps": nominal_pips / 100.0,
                "dynamic_fee": bool(r.dynamic_fee),
            }
        )
    return pd.DataFrame(rows)


def aggregate(
    measured: pd.DataFrame, threshold_bps: float, params: dict[str, Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hook, g in measured.groupby("hook"):
        usable = g[g.usable]
        if usable.empty:
            continue
        charged = usable[usable.excess_bps > threshold_bps]
        excesses = sorted(charged.excess_bps.tolist())
        rate = len(charged) / len(usable)
        median_excess = statistics.median(excesses) if excesses else 0.0

        divergent = len(usable) >= params["min_fills"] and (
            rate >= params["min_charged_rate"]
            or median_excess >= params["min_median_charged_excess_bps"]
        )
        row: dict[str, Any] = {
            "chain": params["chain"],
            "address": hook,
            "fills": int(len(usable)),
            "charged_fills": int(len(charged)),
            "charged_rate": rate,
            "divergent": bool(divergent),
            "coverage": "sampled",
            "dynamic_fee": bool(usable.dynamic_fee.any()),
            "median_take_bps": float(statistics.median(usable.take_bps.tolist())),
        }
        if excesses:
            row["median_charged_excess_bps"] = float(median_excess)
            row["p90_charged_excess_bps"] = float(excesses[max(0, int(0.9 * len(excesses)) - 1)])
            row["max_charged_excess_bps"] = float(max(excesses))
        out.append(row)
    return sorted(out, key=lambda r: (-r["charged_rate"], -r["fills"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    parser.add_argument("--per-hook", type=int, default=8)
    parser.add_argument("--max-hooks", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    cfg = load_config()["metrics"]
    threshold = float(cfg["charged_fill"]["threshold_bps"])
    params = {
        "chain": args.chain,
        "min_fills": int(cfg["divergent_hook"]["min_fills"]),
        "min_charged_rate": float(cfg["divergent_hook"]["min_charged_rate"]),
        "min_median_charged_excess_bps": float(
            cfg["divergent_hook"]["min_median_charged_excess_bps"]
        ),
    }

    fills = eligible_fills(args.chain)
    print(f"  eligible hooked fills: {len(fills):,} across {fills.hook.nunique():,} hooks")

    sample = sample_by_hook(fills, args.per_hook, args.max_hooks, args.seed)
    print(f"  sampling {len(sample):,} fills from {sample.hook.nunique():,} hooks")

    measured = measure(args.chain, sample)

    # Keep the per-fill rows: pipeline C is a time-series view of exactly this data, and
    # re-quoting for it would be both slow and liable to disagree with these numbers.
    cache = path_for("results").parent / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    measured.to_parquet(cache / "b_divergence_fills.parquet", index=False)

    usable = measured[measured.usable]
    print(f"  usable quotes: {len(usable)}/{len(measured)}")

    hooks = aggregate(measured, threshold, params)

    # Sensitivity: the headline must not be an artefact of one threshold.
    sensitivity = []
    for t in cfg["charged_fill"]["sensitivity_threshold_bps"]:
        for mf in cfg["divergent_hook"]["sensitivity_min_fills"]:
            p = {**params, "min_fills": mf}
            rows = aggregate(measured, float(t), p)
            sensitivity.append(
                {
                    "charged_threshold_bps": float(t),
                    "min_fills": int(mf),
                    "divergent_hooks": sum(1 for r in rows if r["divergent"]),
                    "charged_fills": sum(r["charged_fills"] for r in rows),
                }
            )

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "b_divergence",
            "snapshots": [
                snapshot_ref(f"census-{args.chain}"),
                snapshot_ref(f"fills-{args.chain}"),
            ],
        },
        "params": {
            "charged_threshold_bps": threshold,
            "min_fills": params["min_fills"],
            "min_charged_rate": params["min_charged_rate"],
            "min_median_charged_excess_bps": params["min_median_charged_excess_bps"],
            "expected_output_method": "exact",
        },
        "totals": {
            "fills": int(len(usable)),
            "charged_fills": sum(h["charged_fills"] for h in hooks),
            "hooks": len(hooks),
            "divergent_hooks": sum(1 for h in hooks if h["divergent"]),
        },
        "hooks": hooks,
        "sensitivity": sensitivity,
    }
    validate_result("divergence.json", document)

    out: Path = path_for("results") / "divergence.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    t = document["totals"]
    print(f"\n  hooks measured    {t['hooks']}")
    print(f"  fills measured    {t['fills']}")
    print(f"  charged fills     {t['charged_fills']}")
    print(f"  divergent hooks   {t['divergent_hooks']}")
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
