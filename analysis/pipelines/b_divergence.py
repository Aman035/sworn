"""Pipeline B — settled-trade divergence.

For every sampled fill in a hooked pool: re-quote the identical swap against the state
immediately before it, compare with what was actually delivered, and attribute the
difference to the hook. Aggregate per hook into `data/results/divergence.json`.

`docs/METRICS.md` defines every term. Three population rules are enforced here because
they make the comparison well-posed rather than merely convenient:

* a fill is identified by `(txHash, logIndex)` — a Base transaction can carry 126 `Swap`
  events and 37.8% of fills share one;
* only fills that are the sole fill for their pool in their transaction are measured,
  because `vm.rollFork(txHash)` rolls to before the *whole* transaction and a second fill
  in the same pool would be quoted against a state that never existed for it;
* every measured fill is **confirmed against its own transaction trace**, and fills whose
  swap call cannot be recovered are dropped rather than measured.

That third rule is not defensive padding. The `Swap` event is not a record of what the
swapper asked for or got, for two independent reasons:

1. It is emitted *between* `beforeSwap` and `afterSwap`, so its amounts exclude anything
   the hook takes in `afterSwap`. A hook taking 1% there appeared in an earlier run of
   this pipeline as a -101 bps median take: the event made it look like the hook was
   *paying* users 1%.
2. Its sign pattern cannot distinguish exact-input from exact-output. 13% of the fills
   this pipeline selected as "exact-input token0" by event sign were exact-output swaps,
   and were being re-quoted as a swap that never happened.

So `amountSpecified`, `hookData` and the realized output all come from the traced call
(`lib/swapcalls.py`). The event is used only to find candidate fills.

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

from ..lib.cheap_quote import quote_many
from ..lib.compact import SWAP_SHARD_PREFIX, load_shards
from ..lib.config import load_config, path_for, repo_root
from ..lib.deployments import pool_manager
from ..lib.requote import (
    RequoteInput,
    excess_take_bps,
    load_cached_batch,
    result_key,
    run_batch,
)
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_dir, snapshot_ref
from ..lib.swapcalls import SwapCall, pool_id_of, recover_many


def archive_url(chain: str) -> str:
    import os

    url = os.environ.get(f"{chain.upper()}_RPC_ARCHIVE", "")
    if not url:
        raise SystemExit(f"no archive RPC for {chain}")
    return url


def confirm_against_traces(chain: str, sample: pd.DataFrame) -> pd.DataFrame:
    """Replace event-derived swap arguments with what the transaction actually did.

    Adds `req_amount` (signed, as the router passed it), `hook_data`, and `realized`
    (the output from the call's return value, after `afterSwap`). Rows whose call cannot
    be uniquely matched, or which turn out not to be exact-input token0, are marked
    `confirmed = False` and excluded from measurement by `measure`.
    """
    traces = recover_many(archive_url(chain), sample.tx_hash.tolist())
    print(f"  traced {len(traces):,} transactions", flush=True)

    req, hdata, realized, confirmed, reason = [], [], [], [], []
    for _, r in sample.iterrows():
        pid = pool_id_of(r.currency0, r.currency1, int(r.fee_pool), int(r.tick_spacing), r.hook)
        matches = [c for c in traces.get(r.tx_hash, []) if c.ok and c.pool_id == pid]
        call: SwapCall | None = matches[0] if len(matches) == 1 else None

        if call is None:
            req.append(0), hdata.append("0x"), realized.append(0)
            confirmed.append(False)
            reason.append("no unique traced call" if not matches else "ambiguous call")
            continue
        if call.amount_specified >= 0:
            # Exact-output. Indistinguishable from exact-input token0 in the event, and a
            # different quoter call; dropped rather than mis-quoted.
            req.append(call.amount_specified), hdata.append(call.hook_data)
            realized.append(call.amount_out)
            confirmed.append(False), reason.append("exact-output")
            continue

        req.append(call.amount_specified)
        hdata.append(call.hook_data)
        realized.append(call.amount_out)
        confirmed.append(True), reason.append("")

    out = sample.copy()
    out["req_amount"] = req
    out["hook_data"] = hdata
    out["realized"] = realized
    out["confirmed"] = confirmed
    out["drop_reason"] = reason

    kept = int(out.confirmed.sum())
    print(f"  confirmed {kept}/{len(out)} fills against their traces", flush=True)
    for why, n in out[~out.confirmed].drop_reason.value_counts().items():
        print(f"    dropped {n:>4}  {why}", flush=True)
    return out


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


def measure_cheap(chain: str, sample: pd.DataFrame) -> dict[tuple[str, int], int]:
    """Quote every fill at block N-1 via `eth_call`.

    ~3,400x faster than forking per fill, and wrong by exactly the amount earlier
    same-block transactions moved the pool. Measured agreement with the exact method on
    the same fills: median 0.00 bps, 90% within 1 bps. Rows produced this way are flagged
    `approx`.
    """
    url = archive_url(chain)
    pairs = [(f, int(b) - 1) for f, b in zip(_inputs(sample), sample.block_number, strict=True)]

    def show(done: int, total: int, rows: int) -> None:
        if done % 25 == 0 or done == total:
            print(f"    cheap quotes {done}/{total} batches, {rows:,} fills", flush=True)

    print(f"  quoting {len(pairs):,} fills at block N-1 ...", flush=True)
    results = quote_many(url, pool_manager(chain), pairs, progress=show)
    return {result_key(r.tx_hash, r.log_index): r.expected for r in results if r.ok}


def _inputs(sample: pd.DataFrame) -> list[RequoteInput]:
    """The quoter arguments, taken from the traced call rather than the event."""
    return [
        RequoteInput(
            tx_hash=r.tx_hash,
            log_index=int(r.log_index),
            currency0=r.currency0,
            currency1=r.currency1,
            fee=int(r.fee_pool),
            tick_spacing=int(r.tick_spacing),
            hooks=r.hook,
            zero_for_one=True,
            amount_specified=abs(int(r.req_amount)),
            hook_data=r.hook_data,
        )
        for _, r in sample.iterrows()
    ]


def measure(
    chain: str,
    sample: pd.DataFrame,
    *,
    reuse_quotes: bool = False,
    method: str = "exact",
) -> pd.DataFrame:
    inputs = _inputs(sample)
    if method == "cheap":
        by_key = measure_cheap(chain, sample)
        return _rows(chain, sample, by_key, approx=True)

    if reuse_quotes:
        # Re-aggregating with different thresholds must not cost another hour of forked
        # state fetches. The quotes are a pure function of (fill, chain state), so a
        # cached batch is as good as a fresh one — and re-running would produce identical
        # numbers at 30s per fill.
        results = load_cached_batch(f"divergence-{chain}")
        print(f"  reusing {len(results)} cached quotes", flush=True)
    else:
        print(f"  re-quoting {len(inputs)} hooked fills ...", flush=True)
        results = run_batch(chain, inputs, name=f"divergence-{chain}", timeout=7200)
    by_key = {result_key(r.tx_hash, r.log_index): r.expected for r in results if r.ok}
    return _rows(chain, sample, by_key, approx=False)


def _rows(
    chain: str,
    sample: pd.DataFrame,
    by_key: dict[tuple[str, int], int],
    *,
    approx: bool,
) -> pd.DataFrame:
    """Turn quotes into per-fill measurements. Shared by both methods so they cannot
    drift apart in how excess take is computed."""
    rows = []
    for _, r in sample.iterrows():
        expected = by_key.get(result_key(r.tx_hash, int(r.log_index)))
        if expected is None or expected <= 0:
            rows.append(
                {
                    "chain": chain,
                    "hook": r.hook,
                    "block_time": int(r.block_number),
                    "usable": False,
                    "excess_bps": None,
                    "take_bps": None,
                    "approx": approx,
                }
            )
            continue
        # `fee_fill` is the fee actually applied to this swap, which for a dynamic-fee
        # pool is the hook's choice at that moment rather than a property of the key.
        nominal_pips = int(r.fee_fill) if bool(r.dynamic_fee) else int(r.fee_pool)
        # `realized` is the call's return value, not the event's `amount1`: see the module
        # docstring. For a hook that takes in `afterSwap` the two differ by the take.
        realized = int(r.realized)
        shortfall = (expected - realized) / expected
        rows.append(
            {
                "chain": chain,
                "hook": r.hook,
                "block_time": int(r.block_number),
                "usable": True,
                "take_bps": shortfall * 10_000,
                "excess_bps": excess_take_bps(expected, realized, nominal_pips),
                "nominal_bps": nominal_pips / 100.0,
                "dynamic_fee": bool(r.dynamic_fee),
                "approx": approx,
                "hook_data_bytes": max(0, len(r.hook_data) // 2 - 1),
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
            # Every re-quote now uses the `hookData` the router actually passed and is
            # compared against the call's return value, so nothing about the swap is
            # inferred from the event.
            "hook_data_unknown_share": 0.0,
            "hook_data_nonempty_fills": int((usable.hook_data_bytes > 0).sum()),
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
    parser.add_argument(
        "--method",
        choices=("exact", "cheap"),
        default="exact",
        help="exact forks per fill (~33s each); cheap quotes at block N-1 (~0.01s each)",
    )
    parser.add_argument(
        "--reuse-quotes",
        action="store_true",
        help="aggregate from the cached quote batch instead of re-quoting",
    )
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

    # The event told us where to look; the trace tells us what to quote.
    sample = confirm_against_traces(args.chain, sample)
    dropped = sample[~sample.confirmed].drop_reason.value_counts().to_dict()
    sample = sample[sample.confirmed].reset_index(drop=True)
    if sample.empty:
        raise SystemExit("no fills survived trace confirmation")

    measured = measure(args.chain, sample, reuse_quotes=args.reuse_quotes, method=args.method)

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
            # The schema's vocabulary: "cheap" quoting is approximate by construction.
            "expected_output_method": "approx" if args.method == "cheap" else args.method,
            # Quotes carry the hookData the router actually passed, recovered per fill.
            "hook_data_source": "transaction trace",
            "realized_output_source": "PoolManager.swap return value",
        },
        "trace_confirmation": {
            "sampled": int(len(sample) + sum(dropped.values())),
            "confirmed": int(len(sample)),
            "dropped": {str(k): int(v) for k, v in dropped.items()},
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
