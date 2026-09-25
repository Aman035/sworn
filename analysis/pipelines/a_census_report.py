"""Pipeline A3 — assemble `data/results/census.json`.

Joins three inputs into the one file the README, the dashboard and the attestor read:

* the pool census (parquet shards from `a_census`),
* per-hook metadata (`a_hook_metadata`: code hash, proxy slots, verification),
* Uniswap's hooklist (the `allowlisted` column).

Everything here is counting. No thresholds are applied and no hook is judged — that is
Phase 3's job. The census is the denominator, so its only obligation is to be complete
and honest about what it does not know.

    python -m sworn_analysis.pipelines.a_census_report --all
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..lib.compact import load_shards
from ..lib.config import chains, load_config, path_for, repo_root
from ..lib.hookflags import names
from ..lib.hooklist import by_chain_and_address
from ..lib.schema import validate_result
from ..lib.snapshot import read_manifest, script_commit, snapshot_dir, snapshot_ref

TOP_HOOKS = 100
# Flag combinations rarer than this are folded into the tail rather than listed
# individually; with 16k hooks per chain the long tail is mostly one-off deployments.
MIN_COMBINATION_HOOKS = 5


def _hook_metadata(chain: str) -> pd.DataFrame:
    path = snapshot_dir(f"hooks-{chain}") / "hooks.parquet"
    if not path.is_file():
        return pd.DataFrame(columns=["address", "upgradeable", "verified", "code_sha256"])
    return pd.read_parquet(path)


def build_chain(
    chain_name: str, allowlist: dict[tuple[int, str], Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    chain = chains()[chain_name]
    directory = snapshot_dir(f"census-{chain_name}")
    census = load_shards(directory)
    if census.empty:
        raise RuntimeError(f"no census data for {chain_name}")

    try:
        manifest = read_manifest(f"census-{chain_name}")
        block_from, block_to = manifest.block_from, manifest.block_to
    except FileNotFoundError:
        block_from = int(census["block_number"].min())
        block_to = int(census["block_number"].max())

    hooked = census[~census["hookless"]]
    per_hook = (
        hooked.groupby("hook")
        .agg(
            pool_count=("pool_id", "size"),
            flags_bitmap=("flags_bitmap", "first"),
            returns_delta=("returns_delta", "first"),
            touches_swap=("touches_swap", "first"),
            first_seen_block=("block_number", "min"),
            dynamic_fee_pools=("dynamic_fee", "sum"),
        )
        .reset_index()
    )

    meta = _hook_metadata(chain_name)
    if not meta.empty:
        per_hook = per_hook.merge(
            meta[["address", "upgradeable", "verified", "code_sha256", "env_opcodes"]],
            left_on="hook",
            right_on="address",
            how="left",
        ).drop(columns=["address"])
    else:
        for column, default in (
            ("upgradeable", False),
            ("verified", False),
            ("code_sha256", ""),
            ("env_opcodes", ""),
        ):
            per_hook[column] = default

    per_hook["upgradeable"] = per_hook["upgradeable"].fillna(False).astype(bool)
    per_hook["verified"] = per_hook["verified"].fillna(False).astype(bool)
    per_hook["code_sha256"] = per_hook["code_sha256"].fillna("")
    per_hook["allowlisted"] = per_hook["hook"].map(lambda a: (chain.chain_id, a) in allowlist)

    combinations = Counter(int(b) for b in per_hook["flags_bitmap"])
    by_combination = [
        {
            "flags_bitmap": bitmap,
            "hooks": count,
            "names": names(f"0x{bitmap:040x}"),
        }
        for bitmap, count in combinations.most_common()
        if count >= MIN_COMBINATION_HOOKS
    ]

    # Metadata coverage is partial by design (Etherscan is rate limited), so the counts
    # below are "of the hooks we looked at", and the summary says how many that was.
    metadata_covered = int(per_hook["code_sha256"].ne("").sum())

    chain_row: dict[str, Any] = {
        "chain": chain_name,
        "hooks_total": int(per_hook.shape[0]),
        "pools_total": int(census.shape[0]),
        "hooked_pools": int(hooked.shape[0]),
        "block_from": block_from,
        "block_to": block_to,
        "with_returns_delta": int(per_hook["returns_delta"].sum()),
        "dynamic_fee_pools": int(census["dynamic_fee"].sum()),
        "upgradeable": int(per_hook["upgradeable"].sum()),
        "verified": int(per_hook["verified"].sum()),
        "allowlisted": int(per_hook["allowlisted"].sum()),
        "by_flag_combination": by_combination,
    }

    top = per_hook.nlargest(min(TOP_HOOKS, len(per_hook)), "pool_count")
    top_rows = [
        {
            "chain": chain_name,
            "address": r["hook"],
            "pool_count": int(r["pool_count"]),
            "flags_bitmap": int(r["flags_bitmap"]),
            # Volume needs Swap logs and a price source; Phase 3 pulls both. Publishing
            # a guess here would be a fabricated number.
            "volume_usd_30d": None,
            "dynamic_fee": bool(r["dynamic_fee_pools"] > 0),
            "returns_delta": bool(r["returns_delta"]),
            "upgradeable": bool(r["upgradeable"]),
            "verified": bool(r["verified"]),
            "allowlisted": bool(r["allowlisted"]),
            "first_seen_block": int(r["first_seen_block"]),
            **({"bytecode_sha256": r["code_sha256"]} if r["code_sha256"] else {}),
        }
        for _, r in top.iterrows()
    ]

    print(
        f"  {chain_name:<9} {chain_row['pools_total']:>10,} pools  "
        f"{chain_row['hooked_pools']:>10,} hooked  {chain_row['hooks_total']:>7,} hooks  "
        f"(metadata for {metadata_covered:,})"
    )
    return chain_row, top_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", action="append")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    known = chains()
    selected = args.chain or (list(known) if args.all else ["base"])

    available = [c for c in selected if (snapshot_dir(f"census-{c}") / "MANIFEST.json").is_file()]
    skipped = sorted(set(selected) - set(available))
    if skipped:
        print(f"  no completed census for: {', '.join(skipped)} (skipping)")
    if not available:
        print("no completed census snapshots; run a_census first", file=sys.stderr)
        return 1

    allowlist = by_chain_and_address()

    chain_rows: list[dict[str, Any]] = []
    top_hooks: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = [snapshot_ref("hooklist")]

    for name in sorted(available, key=lambda n: known[n].priority):
        row, tops = build_chain(name, allowlist)
        chain_rows.append(row)
        top_hooks.extend(tops)
        snapshots.append(snapshot_ref(f"census-{name}"))

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "a_census_report",
            "snapshots": snapshots,
        },
        "chains": chain_rows,
        "top_hooks": sorted(top_hooks, key=lambda h: -h["pool_count"])[:TOP_HOOKS],
    }

    validate_result("census.json", document)

    out: Path = path_for("results") / "census.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json

    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(repo_root())} ({len(chain_rows)} chain(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
