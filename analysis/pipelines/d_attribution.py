"""Pipeline D — which products routed users into which hooks.

`Swap.sender` is the contract that called `PoolManager.swap`, never the user. Mapping it
to a product turns "a toxic hook exists" into "this product routed users into it", which
is the question an integrator actually has to answer.

The map is hand-curated in `analysis/data/routers.csv` with a source and a confidence per
row. Anything unmapped is reported as `unlabeled`, and the unlabeled share is published:
an attribution table that hides its own coverage is not evidence.

    python -m sworn_analysis.pipelines.d_attribution --chain base
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..lib.compact import SWAP_SHARD_PREFIX, load_shards
from ..lib.config import chains, load_config, path_for, repo_root
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_dir, snapshot_ref

UNLABELED = "unlabeled"


@dataclass(frozen=True)
class RouterRow:
    chain: str
    address: str
    product: str
    contract_name: str
    confidence: float
    source: str


def load_routers(path: Path | None = None) -> dict[tuple[str, str], RouterRow]:
    path = path or repo_root() / load_config()["metrics"]["frontend_attribution"]["router_map"]
    if not path.is_file():
        return {}
    out: dict[tuple[str, str], RouterRow] = {}
    with path.open("r", encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        for r in rows:
            entry = RouterRow(
                chain=r["chain"].strip(),
                address=r["address"].strip().lower(),
                product=r["product"].strip(),
                contract_name=r["contract_name"].strip(),
                confidence=float(r["confidence"]),
                source=r["source"].strip(),
            )
            out[(entry.chain, entry.address)] = entry
    return out


def build(chain_name: str) -> tuple[list[dict[str, Any]], float]:
    if chain_name not in chains():
        raise SystemExit(f"unknown chain {chain_name}")
    routers = load_routers()

    hooked = load_shards(
        snapshot_dir(f"census-{chain_name}"),
        columns=["pool_id", "hook", "hookless"],
        where=lambda part: part[~part.hookless],
    )
    if hooked.empty:
        raise SystemExit(f"no census for {chain_name}")
    hooked_pools = set(hooked.pool_id)

    fills = load_shards(
        snapshot_dir(f"fills-{chain_name}"),
        SWAP_SHARD_PREFIX,
        columns=["pool_id", "sender", "tx_hash", "log_index"],
    )
    if fills.empty:
        raise SystemExit(f"no fills for {chain_name}")

    fills["hooked"] = fills.pool_id.isin(hooked_pools)

    # Divergent hooks, if Phase 3 has produced them. Without that file the table still
    # reports exposure to *hooked* pools, which is the denominator the question needs.
    divergence_path = path_for("results") / "divergence.json"
    divergent: set[str] = set()
    if divergence_path.is_file():
        doc = json.loads(divergence_path.read_text(encoding="utf-8"))
        divergent = {
            h["address"].lower()
            for h in doc.get("hooks", [])
            if h.get("divergent") and h.get("chain") == chain_name
        }
    if divergent:
        pools_of_divergent = set(hooked[hooked.hook.isin(divergent)].pool_id)
        fills["into_divergent"] = fills.pool_id.isin(pools_of_divergent)
    else:
        fills["into_divergent"] = False

    total = len(fills)
    rows: list[dict[str, Any]] = []
    labelled_fills = 0

    for sender, group in fills.groupby("sender"):
        entry = routers.get((chain_name, str(sender).lower()))
        product = entry.product if entry else UNLABELED
        if entry:
            labelled_fills += len(group)

        rows.append(
            {
                "product": product,
                "chain": chain_name,
                "router": str(sender),
                "fills_total": int(len(group)),
                "fills_into_divergent": int(group.into_divergent.sum()),
                "share_of_product_v4_volume": float(group.hooked.mean()),
                "confidence": float(entry.confidence) if entry else 0.0,
                "sources": [entry.source] if entry else [],
            }
        )

    rows.sort(key=lambda r: -r["fills_total"])
    unlabeled_share = 1.0 - (labelled_fills / total if total else 0.0)
    return rows, unlabeled_share


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    rows, unlabeled = build(args.chain)

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "d_attribution",
            "snapshots": [
                snapshot_ref(f"census-{args.chain}"),
                snapshot_ref(f"fills-{args.chain}"),
            ],
        },
        "unlabeled_share": unlabeled,
        "products": rows[: args.top],
    }
    validate_result("attribution.json", document)

    out: Path = path_for("results") / "attribution.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"  routers seen        {len(rows):,}")
    print(f"  unlabeled share     {unlabeled:.1%}")
    print("\n  product              fills      into hooked pools")
    labelled = [r for r in rows if r["product"] != UNLABELED]
    for r in labelled[:10]:
        hooked_share = r["share_of_product_v4_volume"]
        print(
            f"  {r['product']:<18} {r['fills_total']:>10,}   "
            f"{hooked_share:>6.1%}   ({r['router'][:14]}…)"
        )
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
