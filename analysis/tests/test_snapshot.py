"""Snapshot manifests: the thing that makes "reproduce everything" checkable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sworn_analysis.lib import snapshot as snap


@pytest.fixture(autouse=True)
def _snapshots_in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snap, "path_for", lambda key: tmp_path / key)


def _write(name: str, filename: str, content: str) -> Path:
    directory = snap.snapshot_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "x.bin"
    path.write_bytes(b"sworn")
    assert snap.sha256_file(path) == hashlib.sha256(b"sworn").hexdigest()


def test_write_and_read_roundtrip() -> None:
    data = _write("census-base", "census.jsonl", '{"a":1}\n')
    manifest = snap.write_manifest(
        "census-base",
        chain="base",
        chain_id=8453,
        block_from=25_350_988,
        block_to=51_776_736,
        rpc_provider="rough-silent-surf.base-mainnet.quiknode.pro/…97f4",
        rows=1,
        files=[data],
        source="eth_getLogs Initialize",
    )
    assert manifest.files[0].sha256 == snap.sha256_file(data)

    reloaded = snap.read_manifest("census-base")
    assert reloaded.chain_id == 8453
    assert reloaded.block_from == 25_350_988
    assert reloaded.files[0].path == "census.jsonl"


def test_manifest_never_records_a_raw_rpc_url() -> None:
    # The provider field is for attribution, and RPC URLs carry API keys.
    data = _write("census-bnb", "census.jsonl", "{}\n")
    manifest = snap.write_manifest(
        "census-bnb",
        chain="bnb",
        chain_id=56,
        block_from=0,
        block_to=1,
        rpc_provider="host/…abcd",
        rows=0,
        files=[data],
    )
    assert "http" not in manifest.rpc_provider


def test_missing_declared_file_is_an_error() -> None:
    directory = snap.snapshot_dir("census-gone")
    directory.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError, match="not written"):
        snap.write_manifest(
            "census-gone",
            chain="base",
            chain_id=8453,
            block_from=0,
            block_to=1,
            rpc_provider="host",
            rows=0,
            files=[directory / "absent.parquet"],
        )


def test_verify_detects_tampering() -> None:
    data = _write("census-tamper", "census.jsonl", "original\n")
    snap.write_manifest(
        "census-tamper",
        chain="base",
        chain_id=8453,
        block_from=0,
        block_to=1,
        rpc_provider="host",
        rows=1,
        files=[data],
    )
    assert snap.verify_snapshot("census-tamper") == []

    data.write_text("modified\n", encoding="utf-8")
    problems = snap.verify_snapshot("census-tamper")
    assert len(problems) == 1
    assert "sha256" in problems[0]


def test_verify_reports_a_missing_data_file() -> None:
    data = _write("census-missing", "census.jsonl", "x\n")
    snap.write_manifest(
        "census-missing",
        chain="base",
        chain_id=8453,
        block_from=0,
        block_to=1,
        rpc_provider="host",
        rows=1,
        files=[data],
    )
    data.unlink()
    problems = snap.verify_snapshot("census-missing")
    assert "missing" in problems[0]


def test_snapshot_ref_is_shaped_for_the_results_schema() -> None:
    data = _write("census-ref", "census.jsonl", "x\n")
    snap.write_manifest(
        "census-ref",
        chain="base",
        chain_id=8453,
        block_from=10,
        block_to=20,
        rpc_provider="host",
        rows=3,
        files=[data],
    )
    ref = snap.snapshot_ref("census-ref")
    assert set(ref) == {"name", "sha256", "chain", "block_from", "block_to", "rows"}
    assert len(str(ref["sha256"])) == 64


def test_missing_manifest_raises() -> None:
    with pytest.raises(FileNotFoundError, match="no manifest"):
        snap.read_manifest("never-created")


def test_manifest_is_valid_json_on_disk() -> None:
    data = _write("census-json", "census.jsonl", "x\n")
    snap.write_manifest(
        "census-json",
        chain="base",
        chain_id=8453,
        block_from=0,
        block_to=1,
        rpc_provider="host",
        rows=1,
        files=[data],
    )
    raw = (snap.snapshot_dir("census-json") / snap.MANIFEST_NAME).read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["name"] == "census-json"
    assert parsed["script_commit"]
