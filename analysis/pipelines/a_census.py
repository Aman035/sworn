"""Pipeline A — hook and pool census.

Pulls every `Initialize` log from the chain's `PoolManager` deployment block to a pinned
end block, decodes it, and writes a snapshot plus per-chain aggregates. This is the
denominator for everything else: the divergence rate in Phase 3 is meaningless without a
trustworthy count of what exists.

    python -m sworn_analysis.pipelines.a_census --chain base
    python -m sworn_analysis.pipelines.a_census --all --confirmations 64

The pull is resumable. Re-running continues from the last completed chunk rather than
starting over, so an interrupted multi-hour run costs minutes.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..lib.compact import compact, load_shards, shard_paths
from ..lib.config import Chain, chains, path_for, repo_root
from ..lib.deployments import INITIALIZE_TOPIC, load_deployments, pool_manager
from ..lib.logs import fetch_to_jsonl, resume_point
from ..lib.rpc import RpcClient, redact
from ..lib.snapshot import snapshot_dir, write_manifest

# Stay this far behind the head so a reorg cannot change what the snapshot contains.
DEFAULT_CONFIRMATIONS = 64

# Pull this many blocks before compacting. Bounds peak disk to about one slice of raw
# logs rather than the whole chain's history.
SLICE_BLOCKS = 2_000_000


@dataclass
class CensusResult:
    chain: str
    chain_id: int
    block_from: int
    block_to: int
    pools: int
    hooked_pools: int
    hooks: int
    snapshot: str
    parquet: Path


def _progress(chain: str, started: float, span_from: int, chain_start: int, chain_end: int) -> Any:
    """Throttled progress line. Percentage is of the *remaining* span, so a resumed run
    does not claim to start at 0%."""
    last = [0.0]

    def report(done: int, target: int, stats: Any) -> None:
        now = time.time()
        if now - last[0] < 10 and done < target:
            return
        last[0] = now
        # Percentage is of the whole chain; the slice being fetched is only a window.
        span = max(1, chain_end - chain_start)
        pct = 100.0 * min(1.0, max(0.0, (done - chain_start) / span))
        elapsed = now - started
        # Rate is this run's only; percentage is of the whole chain.
        rate = (done - span_from) / max(1e-9, elapsed)
        eta = (chain_end - done) / rate / 60 if rate > 0 else float("inf")
        print(
            f"  {chain}: {done:,}/{chain_end:,} ({pct:5.1f}%) "
            f"{stats.logs:,} logs, chunk<={stats.max_chunk_used:,}, "
            f"{stats.backoffs} backoffs, {elapsed / 60:.1f}m elapsed, ~{eta:.0f}m left",
            flush=True,
        )

    return report


def pull_chain(
    chain: Chain,
    *,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    start_chunk: int = 10_000,
    slice_blocks: int = SLICE_BLOCKS,
) -> CensusResult:
    """Pull, compact and manifest one chain's pool census.

    The pull runs in block slices, compacting to parquet after each one. A single
    uninterrupted pull of Base produces ~14 GB of raw JSON; slicing keeps peak disk to
    roughly one slice's worth while leaving the run fully resumable.
    """
    url = os.environ.get(chain.rpc_env)
    if not url:
        raise RuntimeError(f"{chain.rpc_env} is not set")

    deployment = load_deployments().get(chain.name)
    if deployment is None:
        raise RuntimeError(f"no deployment block for {chain.name}; run scripts/find_deployments.py")

    address = pool_manager(chain.name)
    snapshot = f"census-{chain.name}"
    directory = snapshot_dir(snapshot)
    directory.mkdir(parents=True, exist_ok=True)
    # Prefer an existing uncompressed pull so a run started before compression was added
    # still resumes rather than re-pulling from the deployment block.
    plain = directory / "initialize.jsonl"
    raw = plain if plain.is_file() else directory / "initialize.jsonl.gz"

    from_block = deployment.deployment_block
    undecodable = 0

    with RpcClient(url, timeout=90) as rpc:
        head = rpc.block_number()
        to_block = head - confirmations

        already = resume_point(raw)
        run_start = from_block if already is None else already + 1

        print(
            f"{chain.name}: {from_block:,} -> {to_block:,} "
            f"({to_block - from_block:,} blocks) via {redact(url)}",
            flush=True,
        )
        if already is not None:
            covered = 100.0 * (already - from_block) / max(1, to_block - from_block)
            print(
                f"  {chain.name}: resuming at {run_start:,} ({covered:.1f}% already pulled)",
                flush=True,
            )

        started = time.time()
        cursor = run_start
        while cursor <= to_block:
            slice_end = min(cursor + slice_blocks - 1, to_block)
            fetch_to_jsonl(
                rpc,
                address,
                [INITIALIZE_TOPIC],
                cursor,
                slice_end,
                raw,
                start_chunk=start_chunk,
                progress=_progress(chain.name, started, run_start, from_block, to_block),
            )
            result = compact(raw)
            undecodable += result.undecodable
            if result.rows:
                print(
                    f"  {chain.name}: compacted {result.rows:,} rows "
                    f"(freed {result.freed_bytes / 1e9:.2f} GB), through block {slice_end:,}",
                    flush=True,
                )
            cursor = slice_end + 1

        print(
            f"  {chain.name}: pull complete in {(time.time() - started) / 60:.1f}m",
            flush=True,
        )

    frame = load_shards(directory)
    if undecodable:
        print(f"  {chain.name}: WARNING {undecodable} undecodable logs", file=sys.stderr)

    shards = shard_paths(directory)
    hooked = frame[~frame["hookless"]] if len(frame) else frame
    write_manifest(
        snapshot,
        chain=chain.name,
        chain_id=chain.chain_id,
        block_from=from_block,
        block_to=to_block,
        rpc_provider=redact(url),
        rows=len(frame),
        files=shards,
        source=f"eth_getLogs Initialize from {address}",
        notes=f"{undecodable} undecodable logs" if undecodable else "",
    )

    return CensusResult(
        chain=chain.name,
        chain_id=chain.chain_id,
        block_from=from_block,
        block_to=to_block,
        pools=len(frame),
        hooked_pools=len(hooked),
        hooks=int(hooked["hook"].nunique()) if len(hooked) else 0,
        snapshot=snapshot,
        parquet=shards[-1] if shards else directory,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", action="append", help="chain to pull (repeatable)")
    parser.add_argument("--all", action="store_true", help="every configured chain")
    parser.add_argument("--confirmations", type=int, default=DEFAULT_CONFIRMATIONS)
    parser.add_argument("--start-chunk", type=int, default=10_000)
    parser.add_argument(
        "--slice-blocks",
        type=int,
        default=SLICE_BLOCKS,
        help="blocks to pull before compacting to parquet (bounds peak disk use)",
    )
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    known = chains()

    selected = list(known) if args.all else (args.chain or ["base"])
    unknown = [c for c in selected if c not in known]
    if unknown:
        print(f"unknown chain(s): {unknown}", file=sys.stderr)
        return 2

    path_for("snapshots").mkdir(parents=True, exist_ok=True)

    results: list[CensusResult] = []
    failures: list[str] = []
    for name in sorted(selected, key=lambda n: known[n].priority):
        try:
            results.append(
                pull_chain(
                    known[name], confirmations=args.confirmations, start_chunk=args.start_chunk
                )
            )
        except Exception as exc:  # noqa: BLE001 — one chain must not take down the run
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  {name}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    print("\ncensus pulls complete:")
    for r in results:
        print(
            f"  {r.chain:<9} {r.pools:>8,} pools  {r.hooked_pools:>8,} hooked  "
            f"{r.hooks:>7,} distinct hooks  (blocks {r.block_from:,}-{r.block_to:,})"
        )
    if failures:
        print("\nfailures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
