"""Chunked, adaptive, resumable `eth_getLogs`.

Providers disagree wildly about what they will serve: some cap the block range, some cap
the result count, some just time out. A fixed chunk size is therefore either too small
(Base's census is ~26M blocks) or too large (an immediate 400). This module starts
optimistic, halves on refusal, and grows back after sustained success — and writes every
chunk to disk as it goes so a six-hour pull survives a dropped connection.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .rpc import RpcClient, RpcError

# Phrases providers use when a request was too big. Matching on these lets the fetcher
# back off instead of aborting; anything unrecognised is re-raised, because silently
# retrying a genuine error would produce a quietly incomplete census.
_TOO_BIG = re.compile(
    r"(range|too many|limit|exceed|larger than|max(imum)?\s+(block|result)|"
    r"query returned more than|response size|timeout|took too long)",
    re.IGNORECASE,
)

DEFAULT_START_CHUNK = 10_000
MIN_CHUNK = 8
MAX_CHUNK = 500_000
# Grow only after a run of clean chunks, so one lucky response does not undo the backoff.
GROWTH_AFTER = 8
MAX_RATE_LIMIT_RETRIES = 6
RATE_LIMIT_BASE_DELAY = 1.0


def is_rate_limit(exc: Exception) -> bool:
    """429 means *slow down*, not *ask for less*.

    Shrinking the chunk here would be exactly wrong: it multiplies the number of
    requests. These are retried after a pause at the same width instead.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    return isinstance(exc, RpcError) and exc.code == -32005


def looks_like_range_limit(exc: Exception) -> bool:
    if isinstance(exc, RpcError):
        return bool(_TOO_BIG.search(exc.rpc_message))
    if isinstance(exc, httpx.HTTPStatusError):
        # 413 is unambiguous — the *response* was too big, regardless of the body, which
        # for some providers is HTML rather than JSON-RPC. This is the common case on
        # QuickNode: 10k blocks is fine until a dense stretch blows the size cap.
        if exc.response.status_code == 413:
            return True
        return exc.response.status_code == 400 and bool(_TOO_BIG.search(exc.response.text))
    # A timeout on a wide range is the same signal as an explicit refusal: ask for less.
    return isinstance(exc, httpx.ReadTimeout | httpx.ConnectTimeout)


@dataclass
class FetchStats:
    chunks: int = 0
    logs: int = 0
    backoffs: int = 0
    rate_limit_waits: int = 0
    min_chunk_used: int = MAX_CHUNK
    max_chunk_used: int = 0
    last_block_done: int = -1


class LogFetcher:
    def __init__(
        self,
        rpc: RpcClient,
        address: str,
        topics: list[Any],
        *,
        start_chunk: int = DEFAULT_START_CHUNK,
    ) -> None:
        self.rpc = rpc
        self.address = address
        self.topics = topics
        self.chunk = max(MIN_CHUNK, min(start_chunk, MAX_CHUNK))
        self.stats = FetchStats()
        self._clean_run = 0

    # Seam for tests: a real sleep would make the rate-limit path untestable.
    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _request(self, lo: int, hi: int) -> list[dict[str, Any]]:
        return self.rpc.call(
            "eth_getLogs",
            [
                {
                    "address": self.address,
                    "fromBlock": hex(lo),
                    "toBlock": hex(hi),
                    "topics": self.topics,
                }
            ],
        )

    def fetch_range(
        self, from_block: int, to_block: int
    ) -> Iterator[tuple[int, int, list[dict[str, Any]]]]:
        """Yield `(lo, hi, logs)` for consecutive sub-ranges covering the whole span."""
        lo = from_block
        rate_limit_waits = 0
        while lo <= to_block:
            hi = min(lo + self.chunk - 1, to_block)
            try:
                logs = self._request(lo, hi)
            except Exception as exc:  # noqa: BLE001 — classified immediately below
                if is_rate_limit(exc):
                    if rate_limit_waits >= MAX_RATE_LIMIT_RETRIES:
                        raise
                    delay = RATE_LIMIT_BASE_DELAY * (2**rate_limit_waits)
                    rate_limit_waits += 1
                    self.stats.rate_limit_waits += 1
                    self._sleep(delay)
                    continue
                if not looks_like_range_limit(exc) or self.chunk <= MIN_CHUNK:
                    raise
                self.chunk = max(MIN_CHUNK, self.chunk // 2)
                self.stats.backoffs += 1
                self._clean_run = 0
                continue

            rate_limit_waits = 0

            self.stats.chunks += 1
            self.stats.logs += len(logs)
            self.stats.min_chunk_used = min(self.stats.min_chunk_used, hi - lo + 1)
            self.stats.max_chunk_used = max(self.stats.max_chunk_used, hi - lo + 1)
            self.stats.last_block_done = hi
            yield lo, hi, logs

            lo = hi + 1
            self._clean_run += 1
            if self._clean_run >= GROWTH_AFTER and self.chunk < MAX_CHUNK:
                self.chunk = min(MAX_CHUNK, self.chunk * 2)
                self._clean_run = 0


def resume_point(path: Path) -> int | None:
    """Highest block already covered in a partial JSONL pull, or None if absent.

    Each line carries the chunk's `_to` so a resume never re-requests completed ranges
    and never skips a gap, even if the process died mid-write.
    """
    if not path.is_file():
        return None
    highest: int | None = None
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A torn final line from a killed process: everything before it is good.
                break
            to = record.get("_to")
            if isinstance(to, int):
                highest = to if highest is None else max(highest, to)
    return highest


def fetch_to_jsonl(
    rpc: RpcClient,
    address: str,
    topics: list[Any],
    from_block: int,
    to_block: int,
    out: Path,
    *,
    start_chunk: int = DEFAULT_START_CHUNK,
    progress: Callable[[int, int, FetchStats], None] | None = None,
) -> FetchStats:
    """Pull a log range into a JSONL file, resuming from whatever is already there."""
    out.parent.mkdir(parents=True, exist_ok=True)
    done = resume_point(out)
    start = from_block if done is None else done + 1
    if start > to_block:
        return FetchStats(last_block_done=done or to_block)

    fetcher = LogFetcher(rpc, address, topics, start_chunk=start_chunk)
    with out.open("a", encoding="utf-8") as fh:
        for lo, hi, logs in fetcher.fetch_range(start, to_block):
            fh.write(json.dumps({"_from": lo, "_to": hi, "logs": logs}) + "\n")
            fh.flush()
            if progress:
                progress(hi, to_block, fetcher.stats)
    return fetcher.stats


def iter_logs(path: Path) -> Iterator[dict[str, Any]]:
    """Stream individual log entries out of a JSONL pull."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                break
            yield from record.get("logs", [])
