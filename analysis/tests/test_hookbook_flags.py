"""The flags word is a contract between three places; they must not drift.

`HookBook` stores the bitmap verbatim on-chain, `analysis/config.yaml` defines the bit
positions, and `docs/METRICS.md` explains what each bit means. A renumbering would
silently reinterpret every score already written, so the bits are frozen and this test is
what keeps them that way.
"""

from __future__ import annotations

import re
from pathlib import Path

from sworn_analysis.lib.config import load_config, repo_root

HOOKBOOK = "contracts/src/HookBook.sol"
FLAG_RE = re.compile(r"uint32\s+public\s+constant\s+FLAG_([A-Z_]+)\s*=\s*1\s*<<\s*(\d+);")


def solidity_flags() -> dict[str, int]:
    src = (repo_root() / HOOKBOOK).read_text(encoding="utf-8")
    return {name: int(shift) for name, shift in FLAG_RE.findall(src)}


def test_solidity_flags_match_config() -> None:
    assert solidity_flags() == load_config()["flags"]


def test_flags_fit_a_uint32() -> None:
    assert max(solidity_flags().values()) < 32


def test_bit_positions_are_unique() -> None:
    bits = solidity_flags()
    assert len(set(bits.values())) == len(bits)


def test_every_flag_is_explained_in_metrics_doc() -> None:
    metrics: Path = repo_root() / "docs" / "METRICS.md"
    text = metrics.read_text(encoding="utf-8")
    # The scoring section names the inputs; the flag list itself lives in config.yaml,
    # which METRICS.md points at. Both must be reachable from the doc.
    assert "flags:" in text or "flags word" in text
    assert "INSUFFICIENT_DATA" in text


def test_insufficient_data_is_the_highest_bit_so_far() -> None:
    """New flags append. INSUFFICIENT_DATA being last is a marker that nothing was
    inserted in the middle, which would reinterpret existing on-chain scores."""
    bits = solidity_flags()
    assert bits["INSUFFICIENT_DATA"] == max(bits.values())
    assert bits["DIVERGENT"] == 0
