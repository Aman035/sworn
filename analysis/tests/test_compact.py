"""Incremental compaction: decode raw pulls to parquet, reclaim disk, still resume.

The dangerous property is that compaction *deletes data*. If the progress marker is not
written first, or is not honoured on resume, the next run silently re-pulls from the
deployment block — or worse, skips a range and quietly shrinks the census.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from sworn_analysis.lib.compact import compact, load_shards, next_shard, shard_paths
from sworn_analysis.lib.logs import progress_path, read_progress, record_progress, resume_point

INITIALIZE_TOPIC = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"


def _log(block: int, index: int, hook: str = "0x" + "00" * 20) -> dict[str, Any]:
    """A syntactically valid Initialize log with a chosen hook address."""
    pool = f"0x{block:064x}"
    # Topics are always 32 bytes; an address topic is left-padded into that width.
    c0 = "0x" + "00" * 12 + "11" * 20
    c1 = "0x" + "00" * 12 + "22" * 20
    data = (
        f"{3000:064x}"
        + f"{60:064x}"
        + hook[2:].rjust(64, "0")
        + f"{79228162514264337593543950336:064x}"
        + f"{0:064x}"
    )
    return {
        "topics": [INITIALIZE_TOPIC, pool, c0, c1],
        "data": "0x" + data,
        "blockNumber": hex(block),
        "transactionHash": f"0x{index:064x}",
        "logIndex": hex(index),
    }


def _write_pull(path: Path, chunks: list[tuple[int, int, list[dict[str, Any]]]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for lo, hi, logs in chunks:
            fh.write(json.dumps({"_from": lo, "_to": hi, "logs": logs}) + "\n")


def test_compaction_writes_a_shard_and_frees_the_raw_file(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    _write_pull(raw, [(0, 99, [_log(10, 0), _log(20, 1)]), (100, 199, [_log(150, 0)])])
    size = raw.stat().st_size

    result = compact(raw)

    assert result.rows == 3
    assert result.last_block == 199
    assert result.freed_bytes == size
    assert not raw.exists(), "raw file must be deleted to reclaim disk"
    assert result.shard is not None and result.shard.is_file()


def test_progress_marker_survives_the_deletion(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    _write_pull(raw, [(0, 4_999, [_log(1, 0)])])
    compact(raw)

    # The raw file is gone, but a resume must still know where to continue.
    assert not raw.exists()
    assert read_progress(raw) == 4_999
    assert resume_point(raw) == 4_999


def test_resume_point_prefers_the_further_of_marker_and_raw(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    record_progress(raw, 5_000)
    _write_pull(raw, [(5_001, 6_000, [_log(5_500, 0)])])
    assert resume_point(raw) == 6_000

    # And the marker wins when the raw file lags behind it.
    record_progress(raw, 9_000)
    assert resume_point(raw) == 9_000


def test_progress_marker_never_moves_backwards(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    record_progress(raw, 500)
    record_progress(raw, 100)
    assert read_progress(raw) == 500


def test_progress_path_handles_gzip_names(tmp_path: Path) -> None:
    assert progress_path(tmp_path / "initialize.jsonl").name == "initialize.progress.json"
    assert progress_path(tmp_path / "initialize.jsonl.gz").name == "initialize.progress.json"


def test_corrupt_marker_is_ignored_rather_than_crashing(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    progress_path(raw).write_text("{not json", encoding="utf-8")
    assert read_progress(raw) is None


def test_shards_accumulate_and_are_numbered(tmp_path: Path) -> None:
    for i in range(3):
        raw = tmp_path / "initialize.jsonl"
        _write_pull(raw, [(i * 100, i * 100 + 99, [_log(i * 100 + 1, 0)])])
        compact(raw)

    shards = shard_paths(tmp_path)
    assert [p.name for p in shards] == [
        "pools-part-0000.parquet",
        "pools-part-0001.parquet",
        "pools-part-0002.parquet",
    ]
    assert next_shard(tmp_path).name == "pools-part-0003.parquet"


def test_load_shards_concatenates_and_dedupes(tmp_path: Path) -> None:
    # The same pool appearing in two shards (an overlapping resume) must count once.
    raw = tmp_path / "initialize.jsonl"
    _write_pull(raw, [(0, 99, [_log(10, 0), _log(20, 1)])])
    compact(raw)
    _write_pull(raw, [(80, 199, [_log(20, 1), _log(30, 2)])])
    compact(raw)

    frame = load_shards(tmp_path)
    assert len(frame) == 3
    assert frame["pool_id"].is_unique


def test_hook_columns_are_derived(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    # A hook whose low bits are 0x0088: BEFORE_SWAP + BEFORE_SWAP_RETURNS_DELTA.
    hooked = "0x" + "ab" * 18 + "0088"
    _write_pull(raw, [(0, 99, [_log(10, 0), _log(20, 1, hook=hooked)])])
    compact(raw)

    frame = load_shards(tmp_path)
    hookless_row = frame[frame["hookless"]]
    hooked_row = frame[~frame["hookless"]]

    assert len(hookless_row) == 1
    assert len(hooked_row) == 1
    assert hooked_row.iloc[0]["returns_delta"]
    assert hooked_row.iloc[0]["touches_swap"]
    assert "BEFORE_SWAP_RETURNS_DELTA" in hooked_row.iloc[0]["permissions"]


def test_undecodable_logs_are_counted_not_dropped_silently(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    bad = _log(10, 0)
    bad["data"] = "0x1234"
    _write_pull(raw, [(0, 99, [bad, _log(20, 1)])])

    result = compact(raw)
    assert result.rows == 1
    assert result.undecodable == 1


def test_compacting_a_missing_file_is_a_no_op(tmp_path: Path) -> None:
    result = compact(tmp_path / "absent.jsonl")
    assert result.rows == 0
    assert result.shard is None


def test_torn_final_line_does_not_lose_earlier_chunks(tmp_path: Path) -> None:
    raw = tmp_path / "initialize.jsonl"
    with raw.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_from": 0, "_to": 99, "logs": [_log(10, 0)]}) + "\n")
        fh.write('{"_from": 100, "_to')

    result = compact(raw)
    assert result.rows == 1
    assert result.last_block == 99


def test_empty_shard_directory_loads_as_empty_frame(tmp_path: Path) -> None:
    assert load_shards(tmp_path).equals(pd.DataFrame())


def test_shard_writes_are_atomic(tmp_path: Path) -> None:
    """A killed process must never leave a half-written parquet behind.

    Parquet stores its footer last, so a truncated file is unreadable rather than
    partially readable — exactly the failure that cost a 6.5M-row compaction run.
    """
    raw = tmp_path / "initialize.jsonl"
    _write_pull(raw, [(0, 99, [_log(10, 0), _log(20, 1)])])
    compact(raw)

    assert not list(tmp_path.glob("*.tmp")), "temp file left behind"
    for shard in shard_paths(tmp_path):
        pd.read_parquet(shard)  # raises if incomplete


def test_stray_tmp_file_is_not_treated_as_a_shard(tmp_path: Path) -> None:
    (tmp_path / "pools-part-0000.parquet.tmp").write_bytes(b"garbage")
    assert shard_paths(tmp_path) == []
    # And it must not confuse shard numbering either.
    assert next_shard(tmp_path).name == "pools-part-0000.parquet"


def test_batching_bounds_memory_by_writing_several_shards(tmp_path: Path) -> None:
    """Flushing happens on chunk boundaries, so memory is bounded by
    `batch_rows + one chunk's logs` — not by the size of the whole pull."""
    raw = tmp_path / "initialize.jsonl"
    chunks = [(i * 100, i * 100 + 99, [_log(i * 100 + j, j) for j in range(10)]) for i in range(5)]
    _write_pull(raw, chunks)

    result = compact(raw, batch_rows=10)

    assert result.rows == 50
    assert len(shard_paths(tmp_path)) == 5, "should have flushed per batch, not once at the end"
    assert len(load_shards(tmp_path)) == 50
