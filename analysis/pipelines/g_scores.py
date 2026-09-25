"""Pipeline G — compute per-hook divergence scores into `data/results/scores.json`.

Inputs, in order of how much they say:

* **Divergence** (`divergence.json`, Phase 3) — charged rate and median excess. This is
  the behavioural evidence and carries 55% of the weight.
* **Intermittency** (`intermittency.json`, Phase 3) — regime switching.
* **Probe** (`probe.json`, Phase 4) — environment sensitivity.
* **Census + hook metadata** (Phase 2) — upgradeability, permissions, allowlisting.

Only the last of these exists before Phase 3 completes, so most hooks come out
`INSUFFICIENT_DATA` with no score. That is the correct answer, not a degraded one: a hook
we have not measured has not been cleared.

    python -m sworn_analysis.pipelines.g_scores --chain base
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..lib.compact import load_shards
from ..lib.config import chains, load_config, path_for, repo_root
from ..lib.schema import validate_result
from ..lib.scoring import ScoreInputs, score_hook
from ..lib.snapshot import script_commit, snapshot_dir, snapshot_ref


def _load_optional(name: str) -> dict[str, Any] | None:
    path = path_for("results") / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _index_by_hook(doc: dict[str, Any] | None, chain: str) -> dict[str, dict[str, Any]]:
    if not doc:
        return {}
    return {h["address"].lower(): h for h in doc.get("hooks", []) if h.get("chain") == chain}


def build_scores(chain_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chain = chains()[chain_name]

    census = load_shards(
        snapshot_dir(f"census-{chain_name}"),
        columns=["pool_id", "hook", "hookless", "dynamic_fee", "returns_delta"],
        where=lambda part: part[~part.hookless],
    )
    if census.empty:
        raise RuntimeError(f"no census for {chain_name}")

    per_hook = (
        census.groupby("hook")
        .agg(
            pools=("pool_id", "size"),
            dynamic_fee=("dynamic_fee", "max"),
            returns_delta=("returns_delta", "max"),
        )
        .reset_index()
    )
    del census

    meta_path = snapshot_dir(f"hooks-{chain_name}") / "hooks.parquet"
    if meta_path.is_file():
        meta = pd.read_parquet(meta_path, columns=["address", "upgradeable", "verified"])
        per_hook = per_hook.merge(meta, left_on="hook", right_on="address", how="left").drop(
            columns=["address"]
        )
    else:
        per_hook["upgradeable"] = False
        per_hook["verified"] = False
    per_hook["upgradeable"] = per_hook["upgradeable"].fillna(False).astype(bool)
    per_hook["verified"] = per_hook["verified"].fillna(False).astype(bool)

    from ..lib.hooklist import by_chain_and_address

    allowlist = by_chain_and_address()

    divergence = _index_by_hook(_load_optional("divergence.json"), chain_name)
    intermittency = _index_by_hook(_load_optional("intermittency.json"), chain_name)
    probe = _index_by_hook(_load_optional("probe.json"), chain_name)

    snapshots = [snapshot_ref(f"census-{chain_name}"), snapshot_ref("hooklist")]
    if meta_path.is_file():
        snapshots.append(snapshot_ref(f"hooks-{chain_name}"))
    primary_hash = str(snapshots[0]["sha256"])

    rows: list[dict[str, Any]] = []
    for _, r in per_hook.iterrows():
        address = str(r["hook"])
        d = divergence.get(address, {})
        i = intermittency.get(address, {})
        p = probe.get(address, {})

        inputs = ScoreInputs(
            fills=int(d.get("fills", 0)),
            charged_rate=float(d.get("charged_rate", 0.0)),
            median_excess_bps=float(d.get("median_charged_excess_bps", 0.0)),
            intermittency_crossings=int(i.get("crossings", 0)),
            env_sensitive=bool(p.get("env_sensitive", False)),
            owner_switches=int(i.get("owner_switch_txs", 0)),
            upgradeable=bool(r["upgradeable"]),
            revert_asymmetry=0.0,
            days_since_evidence=0.0,
            dynamic_fee=bool(r["dynamic_fee"]),
            returns_delta=bool(r["returns_delta"]),
            allowlisted=(chain.chain_id, address) in allowlist,
            verified=bool(r["verified"]),
            intermittent=bool(i.get("intermittent", False)),
            divergent=bool(d.get("divergent", False)),
        )
        result = score_hook(inputs)

        rows.append(
            {
                "chain": chain_name,
                "address": address,
                "score": result.score,
                "flags_bitmap": result.flags,
                "flags": result.flag_names,
                "as_of_block": int(snapshots[0].get("block_to") or 0),
                "insufficient_data": result.insufficient_data,
                "inputs": {
                    "charged_rate": inputs.charged_rate,
                    "median_excess_bps": inputs.median_excess_bps,
                    "intermittency_crossings": inputs.intermittency_crossings,
                    "env_sensitive": inputs.env_sensitive,
                    "owner_switches": inputs.owner_switches,
                    "upgradeable": inputs.upgradeable,
                    "revert_asymmetry": inputs.revert_asymmetry,
                    "decay": result.decay,
                },
                "proof": {"snapshot_sha256": primary_hash},
            }
        )

    return rows, snapshots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", action="append")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    known = chains()
    selected = args.chain or (list(known) if args.all else ["base"])
    available = [c for c in selected if (snapshot_dir(f"census-{c}") / "MANIFEST.json").is_file()]
    if not available:
        print("no completed census; run a_census first", file=sys.stderr)
        return 1

    all_rows: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    for name in sorted(available, key=lambda n: known[n].priority):
        rows, snaps = build_scores(name)
        all_rows.extend(rows)
        for s in snaps:
            if s not in all_snapshots:
                all_snapshots.append(s)

        scored = [r for r in rows if r["score"] is not None]
        print(
            f"  {name:<9} {len(rows):>7,} hooks   scored {len(scored):>7,}   "
            f"insufficient data {len(rows) - len(scored):>7,}"
        )

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "g_scores",
            "snapshots": all_snapshots,
        },
        "weights": load_config()["metrics"]["divergence_score"]["weights"],
        "hooks": all_rows,
    }
    validate_result("scores.json", document)

    out: Path = path_for("results") / "scores.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out.relative_to(repo_root())} ({len(all_rows):,} hooks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
