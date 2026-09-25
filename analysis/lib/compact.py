"""Compact a raw log pull into parquet shards and reclaim the disk.

A full-history `Initialize` pull on Base is roughly 14 GB of raw JSON; the decoded rows
are a few hundred MB. Holding the raw file for the whole run is what makes the census
impossible on a normal machine, so it is decoded incrementally and deleted, leaving a
progress marker behind so the pull can still resume.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .census_rows import row
from .events import DecodeError, decode_initialize
from .logs import _open_text, record_progress

SHARD_PREFIX = "pools-part-"


@dataclass
class CompactResult:
    shard: Path | None
    rows: int
    undecodable: int
    last_block: int | None
    freed_bytes: int


def shard_paths(directory: Path) -> list[Path]:
    """Complete shards only — `.parquet.tmp` files are in-progress writes."""
    return sorted(
        p for p in directory.glob(f"{SHARD_PREFIX}*.parquet") if not p.name.endswith(".tmp")
    )


def next_shard(directory: Path) -> Path:
    existing = shard_paths(directory)
    index = 0
    if existing:
        index = max(int(p.stem.removeprefix(SHARD_PREFIX)) for p in existing) + 1
    return directory / f"{SHARD_PREFIX}{index:04d}.parquet"


def _records(raw: Path) -> Iterator[dict[str, Any]]:
    """Stream chunk records, stopping cleanly at a torn final line."""
    with _open_text(raw, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                return


# Rows are flushed to disk in batches. Holding a whole chain in memory first is what
# turns compaction from a fix into a second resource problem: Base alone is ~6.5M pools,
# and as Python dicts that is several GB of RSS.
BATCH_ROWS = 500_000


def compact(raw: Path, *, delete_raw: bool = True, batch_rows: int = BATCH_ROWS) -> CompactResult:
    """Decode `raw` into parquet shards, record progress, and remove the raw file.

    Rows are flushed on chunk boundaries, so peak memory is roughly `batch_rows` plus one
    chunk's worth of logs — independent of how large the raw pull is.
    """
    if not raw.is_file():
        return CompactResult(None, 0, 0, None, 0)

    directory = raw.parent
    size = raw.stat().st_size

    rows: list[dict[str, Any]] = []
    written: list[Path] = []
    total = 0
    undecodable = 0
    last_block: int | None = None

    def flush() -> None:
        """Write one shard atomically.

        A shard written in place is corrupt if the process dies mid-write, and parquet
        gives no partial-read recovery — the footer is at the end. Writing to a temp file
        and renaming means a shard on disk is always complete and readable.
        """
        nonlocal rows, total
        if not rows:
            return
        path = next_shard(directory)
        tmp = path.with_suffix(".parquet.tmp")
        pd.DataFrame(rows).to_parquet(tmp, index=False)
        tmp.replace(path)
        written.append(path)
        total += len(rows)
        rows = []

    for record in _records(raw):
        to = record.get("_to")
        if isinstance(to, int):
            last_block = to if last_block is None else max(last_block, to)
        for log in record.get("logs", []):
            try:
                rows.append(row(decode_initialize(log)))
            except DecodeError:
                undecodable += 1
        if len(rows) >= batch_rows:
            flush()

    flush()
    shard: Path | None = written[-1] if written else None

    # The marker must be written before the raw file is removed, or a crash between the
    # two loses the record of what was already pulled.
    if last_block is not None:
        record_progress(raw, last_block)

    freed = 0
    if delete_raw:
        raw.unlink()
        freed = size

    return CompactResult(shard, total, undecodable, last_block, freed)


def load_shards(directory: Path) -> pd.DataFrame:
    """Concatenate every shard into one frame, deduplicated on pool id."""
    shards = shard_paths(directory)
    if not shards:
        return pd.DataFrame()
    frame = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
    return frame.drop_duplicates(subset=["pool_id"], keep="first").reset_index(drop=True)
