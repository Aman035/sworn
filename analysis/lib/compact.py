"""Compact a raw log pull into parquet shards and reclaim the disk.

A full-history `Initialize` pull on Base is roughly 14 GB of raw JSON; the decoded rows
are a few hundred MB. Holding the raw file for the whole run is what makes the census
impossible on a normal machine, so it is decoded incrementally and deleted, leaving a
progress marker behind so the pull can still resume.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .census_rows import row, swap_row
from .events import DecodeError, decode_initialize, decode_swap
from .logs import _open_text, record_progress

SHARD_PREFIX = "pools-part-"
SWAP_SHARD_PREFIX = "fills-part-"

# (decoder, row builder, shard prefix) per log kind, so the compactor is shared between
# the census and the fill pull rather than duplicated with a different bug in each.
KINDS: dict[str, tuple[Callable[[dict[str, Any]], Any], Callable[[Any], dict[str, Any]], str]] = {
    "initialize": (decode_initialize, row, SHARD_PREFIX),
    "swap": (decode_swap, swap_row, SWAP_SHARD_PREFIX),
}


@dataclass
class CompactResult:
    shard: Path | None
    rows: int
    undecodable: int
    last_block: int | None
    freed_bytes: int


def shard_paths(directory: Path, prefix: str = SHARD_PREFIX) -> list[Path]:
    """Complete shards only — `.parquet.tmp` files are in-progress writes."""
    return sorted(p for p in directory.glob(f"{prefix}*.parquet") if not p.name.endswith(".tmp"))


def next_shard(directory: Path, prefix: str = SHARD_PREFIX) -> Path:
    existing = shard_paths(directory, prefix)
    index = 0
    if existing:
        index = max(int(p.stem.removeprefix(prefix)) for p in existing) + 1
    return directory / f"{prefix}{index:04d}.parquet"


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


def compact(
    raw: Path, *, delete_raw: bool = True, batch_rows: int = BATCH_ROWS, kind: str = "initialize"
) -> CompactResult:
    """Decode `raw` into parquet shards, record progress, and remove the raw file.

    Rows are flushed on chunk boundaries, so peak memory is roughly `batch_rows` plus one
    chunk's worth of logs — independent of how large the raw pull is.
    """
    if not raw.is_file():
        return CompactResult(None, 0, 0, None, 0)

    decoder, build_row, prefix = KINDS[kind]
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
        path = next_shard(directory, prefix)
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
                rows.append(build_row(decoder(log)))
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


def load_shards(
    directory: Path,
    prefix: str = SHARD_PREFIX,
    *,
    columns: list[str] | None = None,
    where: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Concatenate every shard into one frame, deduplicated on its natural key.

    `columns` and `where` are applied **per shard, before concatenating**. That is not an
    optimisation detail: Base has 12.8M fills whose numeric fields are stored as strings
    (they exceed int64), and loading them all before filtering costs the better part of
    ten gigabytes and pushes the machine into swap.
    """
    shards = shard_paths(directory, prefix)
    if not shards:
        return pd.DataFrame()

    parts = []
    for s in shards:
        part = pd.read_parquet(s, columns=columns)
        if where is not None:
            part = where(part)
        if len(part):
            parts.append(part)
    if not parts:
        return pd.DataFrame()
    frame = pd.concat(parts, ignore_index=True)
    # A pool is initialized once; a fill is identified by (tx, log index). An overlapping
    # resume can replay a chunk, so both are deduplicated on what the chain guarantees.
    key = ["pool_id"] if prefix == SHARD_PREFIX else ["tx_hash", "log_index"]
    return frame.drop_duplicates(subset=key, keep="first").reset_index(drop=True)
