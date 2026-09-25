"""Pipeline F — run `hook-probe` over hooks and write `data/results/probe.json`.

Three methods per hook, reported separately rather than merged into a verdict:

* **static** — does the bytecode contain a simulation-distinguishing opcode?
* **differential** — does the quote move when only the environment changes?
* **trace** — does the hook *execute* such an opcode while pricing a swap?

Their disagreement is the finding. On Base, 38.3% of hooks carry a distinguishing opcode
statically; the trace shows most never run one on the swap path.

    python -m sworn_analysis.pipelines.f_probe --chain base --max-hooks 60
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..lib.compact import load_shards
from ..lib.config import chains, load_config, path_for, repo_root
from ..lib.deployments import pool_manager
from ..lib.probe import (
    DISTINGUISHING_OPCODES,
    differential_probe,
    on_swap_path,
    quoter_runtime_code,
    trace_env_opcodes,
)
from ..lib.rpc import RpcClient, RpcError, redact
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_dir, snapshot_ref

PROBE_AMOUNT = 10**15


def static_distinguishing(env_opcodes: str) -> list[str]:
    present = set(env_opcodes.split("|")) if env_opcodes else set()
    return sorted(present & set(DISTINGUISHING_OPCODES))


def run(chain_name: str, max_hooks: int, *, trace: bool = True) -> list[dict[str, Any]]:
    import os

    chain = chains()[chain_name]
    url = os.environ.get(chain.rpc_env)
    if not url:
        raise SystemExit(f"{chain.rpc_env} is not set")

    meta_path = snapshot_dir(f"hooks-{chain_name}") / "hooks.parquet"
    if not meta_path.is_file():
        raise SystemExit(f"no hook metadata for {chain_name}; run a_hook_metadata first")
    meta = pd.read_parquet(meta_path, columns=["address", "pool_count", "env_opcodes"])

    # Probe the hooks that carry the most pools: they are where exposure is.
    targets = meta.nlargest(min(max_hooks, len(meta)), "pool_count")
    wanted = set(targets.address)

    pools = load_shards(
        snapshot_dir(f"census-{chain_name}"),
        columns=["pool_id", "currency0", "currency1", "fee", "tick_spacing", "hook", "hookless"],
        where=lambda part: part[part.hook.isin(wanted)],
    )

    pm = pool_manager(chain_name)
    rows: list[dict[str, Any]] = []

    with RpcClient(url, timeout=180) as rpc:
        print(f"  {chain_name}: probing {len(targets)} hooks via {redact(url)}", flush=True)
        try:
            code = quoter_runtime_code(rpc, pm)
        except (RpcError, FileNotFoundError) as exc:
            raise SystemExit(f"cannot build quoter: {exc}") from exc

        for i, (_, h) in enumerate(targets.iterrows(), start=1):
            pool_rows = pools[pools.hook == h.address]
            static = static_distinguishing(h.env_opcodes)

            row: dict[str, Any] = {
                "chain": chain_name,
                "address": h.address,
                "env_sensitive": False,
                "signals": [],
                "static": {"env_opcodes_present": static},
            }

            if pool_rows.empty:
                rows.append(row)
                continue

            pool = pool_rows.iloc[0].to_dict()
            diff = differential_probe(rpc, chain_name, pm, pool, PROBE_AMOUNT, runtime_code=code)
            row["max_disagreement_bps"] = float(diff.max_disagreement_bps)
            row["signals"] = list(diff.signals)
            row["dynamic"] = {
                "permutations": [
                    {
                        "gas_price_wei": 0 if label == "simulator" else 1_000_000_000,
                        "from_kind": "eoa",
                        "output": None if out is None else str(out),
                        "reverted": bool(diff.reverted.get(label, False)),
                    }
                    for label, out in diff.outputs.items()
                ]
            }

            on_path: list[str] = []
            available = False
            if trace:
                entries, available = trace_env_opcodes(
                    rpc, pm, pool, PROBE_AMOUNT, runtime_code=code
                )
                on_path = on_swap_path(entries, h.address)
            row["trace"] = {"env_opcodes_on_swap_path": on_path, "available": available}

            # The flag requires execution on the swap path, or a measured behavioural
            # difference. Presence in bytecode alone is recorded but never sufficient.
            row["env_sensitive"] = bool(diff.env_sensitive or on_path)
            if on_path and "trace-on-swap-path" not in row["signals"]:
                row["signals"].append("trace-on-swap-path")

            rows.append(row)
            if i % 10 == 0 or i == len(targets):
                print(f"    {i}/{len(targets)} probed", flush=True)

    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    parser.add_argument("--max-hooks", type=int, default=60)
    parser.add_argument("--no-trace", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    rows = run(args.chain, args.max_hooks, trace=not args.no_trace)

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "f_probe",
            "snapshots": [
                snapshot_ref(f"census-{args.chain}"),
                snapshot_ref(f"hooks-{args.chain}"),
            ],
        },
        "hooks": rows,
    }
    validate_result("probe.json", document)

    out: Path = path_for("results") / "probe.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    static_hits = sum(1 for r in rows if r["static"]["env_opcodes_present"])
    traced = [r for r in rows if r.get("trace", {}).get("available")]
    on_path = sum(1 for r in traced if r["trace"]["env_opcodes_on_swap_path"])
    sensitive = sum(1 for r in rows if r["env_sensitive"])
    diff_hits = sum(1 for r in rows if "differential-disagreement" in r["signals"])

    print(f"\n  hooks probed                       {len(rows)}")
    print(f"  static: carries a distinguishing op {static_hits}")
    print(f"  differential: quote moved           {diff_hits}")
    print(f"  trace: executed one on the path     {on_path} (of {len(traced)} traced)")
    print(f"  env_sensitive (trace or behaviour)  {sensitive}")
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
