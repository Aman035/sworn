"""Calibrate the re-quote engine against hookless pools.

`docs/METRICS.md`: a hookless pool has no hook, so the quote at the pre-fill state and
the amount actually delivered must agree. If they do not, the engine is wrong and every
divergence number computed with it is worthless. This is the check that says which.

Two restrictions make the comparison well-posed:

* **Fills are identified by (txHash, logIndex).** A Base transaction can carry up to 126
  `Swap` events and 37.8% of fills share a transaction, so `txHash` alone matches one
  quote against another fill's realized amount.
* **Only fills that are the sole fill for their pool in their transaction.**
  `vm.rollFork(txHash)` rolls to before the *whole* transaction, so for a second fill in
  the same pool the "state immediately before the fill" is not a state that ever existed.
  Quoting it anyway would compare against a fiction.

    .venv/bin/python scripts/calibrate_requote.py --chain base --sample 40
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from dotenv import load_dotenv  # noqa: E402

from lib.compact import SWAP_SHARD_PREFIX, load_shards  # noqa: E402
from lib.config import load_config  # noqa: E402
from lib.requote import RequoteInput, excess_take_bps, result_key, run_batch  # noqa: E402
from lib.snapshot import snapshot_dir  # noqa: E402


def build_population(chain: str):  # noqa: ANN201
    """Eligible hookless fills, assembled without materialising the full join.

    Base has 15.3M pools and 12.8M fills. Merging them outright costs several GB of RSS
    and pushes the machine into swap, so the hookless pools (233k of 15.3M) are selected
    first and the fills are narrowed to that set before anything else happens.
    """
    hookless = load_shards(
        snapshot_dir(f"census-{chain}"),
        columns=["pool_id", "currency0", "currency1", "fee", "tick_spacing", "hook", "hookless"],
        where=lambda part: part[part.hookless],
    )
    if hookless.empty:
        raise SystemExit(f"missing census for {chain}")
    hookless = hookless.drop(columns=["hookless"])

    wanted = set(hookless.pool_id)
    fills = load_shards(
        snapshot_dir(f"fills-{chain}"),
        SWAP_SHARD_PREFIX,
        columns=["pool_id", "amount0", "amount1", "tx_hash", "log_index"],
        where=lambda part: part[part.pool_id.isin(wanted)],
    )
    if fills.empty:
        raise SystemExit(f"missing fills for {chain}")

    m = fills.merge(hookless, on="pool_id", how="inner", suffixes=("_fill", "_pool"))
    del fills, hookless

    m["a0"] = m.amount0.map(int)
    m["a1"] = m.amount1.map(int)

    # Exactly one fill per (tx, pool): see the module docstring.
    counts = m.groupby(["tx_hash", "pool_id"]).size().rename("n")
    m = m.join(counts, on=["tx_hash", "pool_id"])
    m = m[m.n == 1]

    # Exact-input with token0 in; both sides non-zero so a ratio means something.
    return m[(m.a0 < 0) & (m.a1 > 0)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    cfg = load_config()["metrics"]["expected_output"]
    tolerance = float(cfg["calibration_max_abs_excess_bps"])
    required = float(cfg["calibration_min_pass_rate"])

    pop = build_population(args.chain)
    print(f"  eligible hookless fills: {len(pop):,}")
    if pop.empty:
        raise SystemExit("no eligible fills")

    sample = pop.sample(n=min(args.sample, len(pop)), random_state=args.seed)

    fills = [
        RequoteInput(
            tx_hash=r.tx_hash,
            log_index=int(r.log_index),
            currency0=r.currency0,
            currency1=r.currency1,
            fee=int(r.fee),
            tick_spacing=int(r.tick_spacing),
            hooks=r.hook,
            zero_for_one=True,
            amount_specified=abs(r.a0),
        )
        for _, r in sample.iterrows()
    ]

    print(f"  re-quoting {len(fills)} fills on {args.chain} ...", flush=True)
    results = run_batch(args.chain, fills, name="calib")
    by_key = {result_key(r.tx_hash, r.log_index): r for r in results}

    rows = []
    for _, r in sample.iterrows():
        q = by_key.get(result_key(r.tx_hash, int(r.log_index)))
        if q is None or not q.ok or q.expected == 0:
            rows.append(
                (r.tx_hash_fill, None, r.a1, None, q.error if q else "no result")
            )
            continue
        rows.append(
            (
                r.tx_hash_fill,
                q.expected,
                r.a1,
                excess_take_bps(q.expected, r.a1, int(r.fee)),
                "",
            )
        )

    usable = [x for x in rows if x[3] is not None]
    unusable = [x for x in rows if x[3] is None]

    print(f"\n  usable quotes: {len(usable)}/{len(rows)}")
    for tx, exp, real, ex, err in rows[:10]:
        if exp is None:
            print(f"    {tx[:14]}… unusable: {err}")
        else:
            print(f"    {tx[:14]}… ratio={exp / real:.6f}  excess={ex:8.3f} bps")

    if not usable:
        print("\n  CALIBRATION FAILED: no usable quotes", file=sys.stderr)
        return 1

    excesses = sorted(x[3] for x in usable)
    ratios = sorted(x[1] / x[2] for x in usable)
    within = sum(1 for e in excesses if e <= tolerance)
    rate = within / len(excesses)

    print(f"\n  ratio expected/realized : median={statistics.median(ratios):.6f}")
    print(
        f"  excess take bps         : median={statistics.median(excesses):.3f}  max={max(excesses):.3f}"
    )
    print(
        f"  within {tolerance} bps          : {within}/{len(excesses)} ({rate:.0%})  required >= {required:.0%}"
    )
    if unusable:
        print(f"  unusable                : {len(unusable)} (reported, not hidden)")

    if rate < required:
        print("\n  CALIBRATION FAILED — the re-quote engine is wrong.", file=sys.stderr)
        return 1
    print("\n  calibration passed: hookless pools show no excess take")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
