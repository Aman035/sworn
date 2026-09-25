"""Pipeline C — intermittency: hooks that are toxic only some of the time.

This is the pattern allowlists structurally cannot catch. Enso observed a pool toxic for
roughly 423 of 718 hours and toggled 26 times across 48 windows; a registry refreshed on
human timescales is always one toggle behind.

Reads the per-fill measurements Phase B produced, buckets them by hour, and counts how
often a hook's charged rate crosses the threshold. An hour with too few fills cannot count
as a crossing — otherwise a single fill flips the regime.

    python -m sworn_analysis.pipelines.c_intermittency --chain base
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..lib.config import load_config, path_for, repo_root
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_ref

MEASUREMENTS = "b_divergence_fills.parquet"


def _block_to_epoch(chain: str):  # noqa: ANN202
    """Map a block number to an approximate unix time.

    Anchored on the fills snapshot: its manifest records the block it ended at and when it
    was taken, and the chain's block time is a measured constant. Fetching a timestamp per
    block would be millions of extra RPC calls to gain a precision that hourly buckets
    cannot use — but the approximation is real, so results say so.
    """
    from ..lib.snapshot import read_manifest
    from .b_fills import BLOCK_SECONDS

    manifest = read_manifest(f"fills-{chain}")
    anchor_block = manifest.block_to
    anchor_epoch = int(
        datetime.strptime(manifest.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    )
    seconds = BLOCK_SECONDS.get(chain, 2.0)

    def convert(block: int) -> int:
        return int(anchor_epoch - (anchor_block - int(block)) * seconds)

    return convert


def crossings(series: list[bool]) -> int:
    """How many times the regime flipped between toxic and not."""
    return sum(1 for a, b in zip(series, series[1:], strict=False) if a != b)


def build(chain: str) -> list[dict[str, Any]]:
    cfg = load_config()["metrics"]
    threshold = float(cfg["charged_fill"]["threshold_bps"])
    window_days = int(cfg["intermittent"]["window_days"])
    min_crossings = int(cfg["intermittent"]["min_crossings"])
    min_per_bucket = int(cfg["intermittent"]["min_fills_per_bucket"])

    path = path_for("results").parent / "cache" / MEASUREMENTS
    if not path.is_file():
        raise SystemExit(
            f"no per-fill measurements at {path}; run b_divergence first "
            "(intermittency is a time-series view of the same data, not a second pull)"
        )
    frame = pd.read_parquet(path)
    frame = frame[(frame.chain == chain) & frame.usable]
    if frame.empty:
        raise SystemExit(f"no usable measurements for {chain}")

    frame["hour"] = pd.to_datetime(
        frame.block_time.map(_block_to_epoch(chain)), unit="s", utc=True
    ).dt.floor("h")
    frame["charged"] = frame.excess_bps > threshold

    rows: list[dict[str, Any]] = []
    for hook, g in frame.groupby("hook"):
        hourly = (
            g.groupby("hour")
            .agg(fills=("charged", "size"), charged_fills=("charged", "sum"))
            .reset_index()
            .sort_values("hour")
        )
        hourly["charged_rate"] = hourly.charged_fills / hourly.fills

        # Only hours with enough fills can define a regime.
        solid = hourly[hourly.fills >= min_per_bucket]
        regimes = (solid.charged_rate > 0).tolist()
        n_crossings = crossings(regimes)
        toxic_hours = int((solid.charged_rate > 0).sum())

        rows.append(
            {
                "chain": chain,
                "address": str(hook),
                "window_days": window_days,
                "crossings": int(n_crossings),
                "toxic_hour_share": float(toxic_hours / len(solid)) if len(solid) else 0.0,
                "intermittent": bool(n_crossings >= min_crossings),
                "hourly": [
                    {
                        "ts": r.hour.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "fills": int(r.fills),
                        "charged_fills": int(r.charged_fills),
                        "charged_rate": float(r.charged_rate),
                    }
                    for r in hourly.itertuples()
                ][:500],
            }
        )
    return sorted(rows, key=lambda r: -r["crossings"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    hooks = build(args.chain)

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "c_intermittency",
            "snapshots": [snapshot_ref(f"fills-{args.chain}")],
        },
        "hooks": hooks,
    }
    validate_result("intermittency.json", document)

    out: Path = path_for("results") / "intermittency.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    intermittent = sum(1 for h in hooks if h["intermittent"])
    print(f"  hooks with a time series   {len(hooks)}")
    print(f"  intermittent               {intermittent}")
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
