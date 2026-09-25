"""Decode a raw log pull into parquet shards and delete the raw file.

Run this when a long census pull is eating the disk. It is safe at any time: the pull
resumes from the progress marker the compaction leaves behind.

    .venv/bin/python scripts/compact_pull.py --chain base
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from lib.compact import compact, load_shards, shard_paths  # noqa: E402
from lib.snapshot import snapshot_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", required=True)
    parser.add_argument("--keep-raw", action="store_true")
    args = parser.parse_args()

    directory = snapshot_dir(f"census-{args.chain}")
    if not directory.is_dir():
        print(f"no snapshot directory for {args.chain}", file=sys.stderr)
        return 1

    candidates = [directory / "initialize.jsonl", directory / "initialize.jsonl.gz"]
    raw = next((c for c in candidates if c.is_file()), None)
    if raw is None:
        print(
            f"{args.chain}: nothing to compact ({len(shard_paths(directory))} shard(s) present)"
        )
        return 0

    print(
        f"{args.chain}: compacting {raw.name} ({raw.stat().st_size / 1e9:.2f} GB)...",
        flush=True,
    )
    result = compact(raw, delete_raw=not args.keep_raw)

    print(f"  rows            {result.rows:,}")
    print(f"  undecodable     {result.undecodable:,}")
    print(
        f"  last block      {result.last_block:,}"
        if result.last_block
        else "  last block      -"
    )
    print(f"  shard           {result.shard.name if result.shard else '-'}")
    print(f"  freed           {result.freed_bytes / 1e9:.2f} GB")

    total = load_shards(directory)
    print(
        f"  total pools so far {len(total):,} across {len(shard_paths(directory))} shard(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
