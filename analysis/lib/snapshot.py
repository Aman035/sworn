"""Pinned data snapshots.

Every result file names the snapshot it was computed from, and every snapshot carries a
manifest with a sha256. That is what makes "reproduce everything" a command rather than a
claim: re-pull the same block range, hash it, compare.

Layout:

    data/snapshots/<name>/
      MANIFEST.json      committed
      <files>            gitignored (parquet/jsonl can be large)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import path_for

MANIFEST_NAME = "MANIFEST.json"
_HASH_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def script_commit() -> str:
    """The commit the data was produced at, with a `-dirty` marker when it matters.

    A snapshot produced from uncommitted code is not reproducible, so the manifest says
    so rather than recording a commit that does not describe the code that ran.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(["git", "diff", "--quiet"], capture_output=True).returncode != 0
        return f"{sha}-dirty" if dirty else sha
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


@dataclass
class SnapshotFile:
    path: str
    sha256: str
    bytes: int
    rows: int | None = None


@dataclass
class Manifest:
    name: str
    chain: str
    chain_id: int
    block_from: int
    block_to: int
    rpc_provider: str
    script_commit: str
    created_at: str
    rows: int
    source: str = ""
    notes: str = ""
    files: list[SnapshotFile] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=False) + "\n"


def snapshot_dir(name: str) -> Path:
    return path_for("snapshots") / name


def write_manifest(
    name: str,
    *,
    chain: str,
    chain_id: int,
    block_from: int,
    block_to: int,
    rpc_provider: str,
    rows: int,
    files: list[Path],
    source: str = "",
    notes: str = "",
) -> Manifest:
    """Hash every data file and record the manifest beside them."""
    directory = snapshot_dir(name)
    directory.mkdir(parents=True, exist_ok=True)

    entries = [
        SnapshotFile(path=f.name, sha256=sha256_file(f), bytes=f.stat().st_size)
        for f in files
        if f.is_file()
    ]
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        raise FileNotFoundError(f"snapshot {name}: declared files not written: {missing}")

    manifest = Manifest(
        name=name,
        chain=chain,
        chain_id=chain_id,
        block_from=block_from,
        block_to=block_to,
        rpc_provider=rpc_provider,
        script_commit=script_commit(),
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rows=rows,
        source=source,
        notes=notes,
        files=entries,
    )
    (directory / MANIFEST_NAME).write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def read_manifest(name: str) -> Manifest:
    path = snapshot_dir(name) / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no manifest for snapshot {name!r} at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    files = [SnapshotFile(**f) for f in raw.pop("files", [])]
    return Manifest(**raw, files=files)


def verify_snapshot(name: str) -> list[str]:
    """Re-hash a snapshot's files against its manifest. Empty list means intact."""
    manifest = read_manifest(name)
    directory = snapshot_dir(name)
    problems: list[str] = []
    for entry in manifest.files:
        path = directory / entry.path
        if not path.is_file():
            problems.append(f"{name}/{entry.path}: missing (data files are gitignored)")
            continue
        actual = sha256_file(path)
        if actual != entry.sha256:
            problems.append(
                f"{name}/{entry.path}: sha256 {actual[:12]}… != manifest {entry.sha256[:12]}…"
            )
    return problems


def snapshot_ref(name: str) -> dict[str, object]:
    """The `meta.snapshots[]` entry a result file embeds to point back here."""
    from .config import chains

    m = read_manifest(name)
    primary = m.files[0].sha256 if m.files else "0" * 64
    ref: dict[str, object] = {
        "name": m.name,
        "sha256": primary,
        "block_from": m.block_from,
        "block_to": m.block_to,
        "rows": m.rows,
    }
    # Some snapshots are not chain-scoped (the hooklist covers 21 chains at once). The
    # schema's `chain` is a strict enum, so a cross-chain snapshot omits the field rather
    # than inventing a value for it.
    if m.chain in chains():
        ref["chain"] = m.chain
    return ref
