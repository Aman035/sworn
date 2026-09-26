"""Independent reconciliation of the census.

The census is the denominator for every later number, so it is checked against a second
implementation that shares as little as possible with the first:

* it re-requests logs straight from the node rather than reading the snapshot;
* it decodes the hook address by **byte offset** into the log data, not through
  `eth_abi`, so a mistake in the ABI decoder cannot be reproduced identically here;
* it samples random block windows across the whole range rather than trusting the
  contiguity of the pull.

A disagreement beyond the tolerance means the pull skipped a range, the decoder is wrong,
or the snapshot is stale. All three are silent failures otherwise.

    python -m sworn_analysis.pipelines.verify_census --chain base --windows 40
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from ..lib.compact import load_shards
from ..lib.config import chains, repo_root
from ..lib.deployments import INITIALIZE_TOPIC, load_deployments, pool_manager
from ..lib.rpc import RpcClient, redact
from ..lib.snapshot import read_manifest, snapshot_dir

# Each Initialize log's data is 5 words. The hook address is the third, right-aligned.
HOOK_WORD_INDEX = 2
WORD = 32
DEFAULT_TOLERANCE = 0.05
DEFAULT_WINDOWS = 40
DEFAULT_WINDOW_BLOCKS = 2_000


def hook_from_data_bytes(data_hex: str) -> str:
    """Pull the hook address out of the log data by offset, with no ABI machinery."""
    raw = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
    if len(raw) != 5 * WORD:
        raise ValueError(f"expected 160 bytes of Initialize data, got {len(raw)}")
    word = raw[HOOK_WORD_INDEX * WORD : (HOOK_WORD_INDEX + 1) * WORD]
    return "0x" + word[-20:].hex()


@dataclass
class Reconciliation:
    chain: str
    windows: int
    blocks_sampled: int
    independent_pools: int
    snapshot_pools: int
    independent_hooks: int
    snapshot_hooks: int

    @staticmethod
    def _delta(a: int, b: int) -> float:
        if a == 0 and b == 0:
            return 0.0
        return abs(a - b) / max(1, max(a, b))

    @property
    def pool_delta(self) -> float:
        return self._delta(self.independent_pools, self.snapshot_pools)

    @property
    def hook_delta(self) -> float:
        return self._delta(self.independent_hooks, self.snapshot_hooks)

    def passed(self, tolerance: float) -> bool:
        return self.pool_delta <= tolerance and self.hook_delta <= tolerance


def reconcile(
    chain_name: str,
    *,
    windows: int = DEFAULT_WINDOWS,
    window_blocks: int = DEFAULT_WINDOW_BLOCKS,
    seed: int = 20260925,
) -> Reconciliation:
    chain = chains()[chain_name]
    url = os.environ.get(chain.rpc_env)
    if not url:
        raise RuntimeError(f"{chain.rpc_env} is not set")

    directory = snapshot_dir(f"census-{chain_name}")
    frame = load_shards(directory)
    if frame.empty:
        raise RuntimeError(f"no census shards for {chain_name}; run the census pipeline first")

    deployment = load_deployments()[chain_name]
    try:
        manifest = read_manifest(f"census-{chain_name}")
        hi = manifest.block_to
    except FileNotFoundError:
        hi = int(frame["block_number"].max())
    lo = deployment.deployment_block

    rng = random.Random(seed)
    starts = sorted(rng.randint(lo, max(lo, hi - window_blocks)) for _ in range(windows))

    independent_pools: set[str] = set()
    independent_hooks: set[str] = set()
    sampled_ranges: list[tuple[int, int]] = []

    address = pool_manager(chain_name)
    with RpcClient(url, timeout=60) as rpc:
        for start in starts:
            end = min(hi, start + window_blocks - 1)
            logs = rpc.call(
                "eth_getLogs",
                [
                    {
                        "address": address,
                        "fromBlock": hex(start),
                        "toBlock": hex(end),
                        "topics": [INITIALIZE_TOPIC],
                    }
                ],
            )
            sampled_ranges.append((start, end))
            for log in logs:
                independent_pools.add(log["topics"][1].lower())
                hook = hook_from_data_bytes(log["data"])
                if int(hook, 16) != 0:
                    independent_hooks.add(hook)

    # The same windows, read out of the snapshot.
    mask = False
    for start, end in sampled_ranges:
        window = (frame["block_number"] >= start) & (frame["block_number"] <= end)
        mask = window if mask is False else (mask | window)
    subset = frame[mask]

    snapshot_hooks = set(subset.loc[~subset["hookless"], "hook"].str.lower())

    print(f"  reconciling {chain_name} via {redact(url)}")
    print(
        f"    windows          {len(sampled_ranges)} x {window_blocks} blocks in [{lo:,}, {hi:,}]"
    )

    return Reconciliation(
        chain=chain_name,
        windows=len(sampled_ranges),
        blocks_sampled=sum(e - s + 1 for s, e in sampled_ranges),
        independent_pools=len(independent_pools),
        snapshot_pools=len(set(subset["pool_id"].str.lower())),
        independent_hooks=len(independent_hooks),
        snapshot_hooks=len(snapshot_hooks),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", action="append")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--windows", type=int, default=DEFAULT_WINDOWS)
    parser.add_argument("--window-blocks", type=int, default=DEFAULT_WINDOW_BLOCKS)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    known = chains()
    selected = list(known) if args.all else (args.chain or ["base"])

    failures: list[str] = []
    for name in selected:
        directory = Path(snapshot_dir(f"census-{name}"))
        if not directory.is_dir():
            print(f"  -- {name}: no snapshot, skipping")
            continue
        try:
            result = reconcile(name, windows=args.windows, window_blocks=args.window_blocks)
        except Exception as exc:  # noqa: BLE001. Report and continue to the next chain
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue

        ok = result.passed(args.tolerance)
        for label, indep, snap, delta in (
            ("pools", result.independent_pools, result.snapshot_pools, result.pool_delta),
            ("hooks", result.independent_hooks, result.snapshot_hooks, result.hook_delta),
        ):
            print(
                f"    {label:<7} independent {indep:>8,}  "
                f"snapshot {snap:>8,}  delta {delta:6.2%}"
            )
        print(f"    {'ok' if ok else 'FAIL'} (tolerance {args.tolerance:.0%})\n")
        if not ok:
            failures.append(
                f"{name}: pool delta {result.pool_delta:.2%}, hook delta {result.hook_delta:.2%}"
            )

    if failures:
        print("reconciliation failures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("census reconciles with an independent count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
