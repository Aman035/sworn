"""Pipeline B (part 1) — pull settled fills.

Every `Swap` event on the target chain over a fixed window. This is the raw material for
divergence (what was actually delivered), intermittency (when), and attribution (who
routed the user there).

The window is bounded deliberately: `docs/METRICS.md` defines intermittency over 30 days,
and Base alone produces roughly ten million fills in that period. Pulling since genesis
would multiply the cost without changing any published number.

    python -m sworn_analysis.pipelines.b_fills --chain base --days 30
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

from dotenv import load_dotenv

from ..lib.compact import SWAP_SHARD_PREFIX, compact, load_shards, shard_paths
from ..lib.config import Chain, chains, repo_root
from ..lib.deployments import SWAP_TOPIC, pool_manager
from ..lib.logs import fetch_to_jsonl, resume_point
from ..lib.rpc import RpcClient, redact
from ..lib.snapshot import snapshot_dir, write_manifest

DEFAULT_DAYS = 30
DEFAULT_CONFIRMATIONS = 64
SLICE_BLOCKS = 200_000

# Fills are far denser than pool creations, so start smaller than the census does and let
# the fetcher grow into whatever the provider allows.
DEFAULT_START_CHUNK = 2_000

# Seconds per block, used only to turn `--days` into a block span. Measured, not guessed;
# the manifest records the actual block range that resulted.
BLOCK_SECONDS: dict[str, float] = {
    "base": 2.0,
    "bnb": 0.75,
    "arbitrum": 0.25,
    "unichain": 1.0,
    "mainnet": 12.0,
    "polygon": 2.0,
}


def _coverage_start(directory) -> int | None:  # noqa: ANN001
    """Lowest block already represented in this snapshot's shards, if any."""
    shards = shard_paths(directory, SWAP_SHARD_PREFIX)
    if not shards:
        return None
    import pandas as pd

    return min(
        int(pd.read_parquet(s, columns=["block_number"])["block_number"].min()) for s in shards
    )


@dataclass
class FillsResult:
    chain: str
    fills: int
    block_from: int
    block_to: int


def _progress(chain: str, started: float, run_start: int, chain_end: int):  # noqa: ANN202
    last = [0.0]

    def report(done: int, target: int, stats) -> None:  # noqa: ANN001
        now = time.time()
        if now - last[0] < 15 and done < target:
            return
        last[0] = now
        span = max(1, chain_end - run_start)
        pct = 100.0 * min(1.0, max(0.0, (done - run_start) / span))
        elapsed = now - started
        rate = (done - run_start) / max(1e-9, elapsed)
        eta = (chain_end - done) / rate / 60 if rate > 0 else float("inf")
        print(
            f"  {chain}: {done:,}/{chain_end:,} ({pct:5.1f}%) {stats.logs:,} fills, "
            f"chunk<={stats.max_chunk_used:,}, {stats.backoffs} backoffs, ~{eta:.0f}m left",
            flush=True,
        )

    return report


def pull_fills(
    chain: Chain,
    *,
    days: int = DEFAULT_DAYS,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    slice_blocks: int = SLICE_BLOCKS,
    start_chunk: int = DEFAULT_START_CHUNK,
) -> FillsResult:
    url = os.environ.get(chain.rpc_env)
    if not url:
        raise RuntimeError(f"{chain.rpc_env} is not set")

    snapshot = f"fills-{chain.name}"
    directory = snapshot_dir(snapshot)
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / "swaps.jsonl.gz"

    address = pool_manager(chain.name)
    seconds = BLOCK_SECONDS.get(chain.name, 2.0)
    span = int(days * 24 * 3600 / seconds)

    undecodable = 0
    with RpcClient(url, timeout=120) as rpc:
        head = rpc.block_number()
        to_block = head - confirmations
        from_block = max(0, to_block - span)

        already = resume_point(raw)

        print(
            f"{chain.name}: fills over {days}d = blocks {from_block:,} -> {to_block:,} "
            f"({to_block - from_block:,}) via {redact(url)}",
            flush=True,
        )

        # Resume only extends forward. A larger `--days` moves the window's *start*
        # earlier, and continuing from the old high-water mark would leave that earlier
        # stretch unpulled while the manifest claimed the full window — a snapshot that
        # lies about its own coverage. Refuse instead.
        covered_from = _coverage_start(directory)
        if already is not None and covered_from is not None and from_block < covered_from:
            raise RuntimeError(
                f"existing {snapshot} covers from block {covered_from:,}, but a {days}d "
                f"window starts at {from_block:,}. Delete data/snapshots/{snapshot} and "
                f"re-pull rather than produce a snapshot that under-covers its stated window."
            )

        run_start = from_block if already is None else max(from_block, already + 1)
        if already is not None:
            print(f"  {chain.name}: resuming at {run_start:,}", flush=True)

        started = time.time()
        cursor = run_start
        while cursor <= to_block:
            slice_end = min(cursor + slice_blocks - 1, to_block)
            fetch_to_jsonl(
                rpc,
                address,
                [SWAP_TOPIC],
                cursor,
                slice_end,
                raw,
                start_chunk=start_chunk,
                progress=_progress(chain.name, started, run_start, to_block),
            )
            result = compact(raw, kind="swap")
            undecodable += result.undecodable
            if result.rows:
                print(
                    f"  {chain.name}: compacted {result.rows:,} fills "
                    f"(freed {result.freed_bytes / 1e9:.2f} GB) through {slice_end:,}",
                    flush=True,
                )
            cursor = slice_end + 1

        print(f"  {chain.name}: fills pulled in {(time.time() - started) / 60:.1f}m", flush=True)

    frame = load_shards(directory, SWAP_SHARD_PREFIX)
    write_manifest(
        snapshot,
        chain=chain.name,
        chain_id=chain.chain_id,
        block_from=from_block,
        block_to=to_block,
        rpc_provider=redact(url),
        rows=len(frame),
        files=shard_paths(directory, SWAP_SHARD_PREFIX),
        source=f"eth_getLogs Swap from {address}",
        notes=f"{days}d window" + (f", {undecodable} undecodable" if undecodable else ""),
    )
    return FillsResult(chain.name, len(frame), from_block, to_block)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", action="append")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--confirmations", type=int, default=DEFAULT_CONFIRMATIONS)
    parser.add_argument("--slice-blocks", type=int, default=SLICE_BLOCKS)
    parser.add_argument("--start-chunk", type=int, default=DEFAULT_START_CHUNK)
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    known = chains()
    selected = args.chain or ["base"]

    failures: list[str] = []
    for name in selected:
        if name not in known:
            failures.append(f"unknown chain {name}")
            continue
        try:
            r = pull_fills(
                known[name],
                days=args.days,
                confirmations=args.confirmations,
                slice_blocks=args.slice_blocks,
                start_chunk=args.start_chunk,
            )
            print(f"  {r.chain}: {r.fills:,} fills in blocks {r.block_from:,}-{r.block_to:,}")
        except Exception as exc:  # noqa: BLE001 — continue to the next chain
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAIL {name}: {exc}", file=sys.stderr)

    if failures:
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
