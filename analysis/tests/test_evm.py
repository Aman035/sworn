"""Static bytecode analysis, checked against really-compiled contracts.

The decisive property: PUSH immediates must not be mistaken for opcodes. `NoEnvReads`
contains a constant made of 0x3a and 0x41 bytes precisely so that a naive scanner fails
this file loudly.
"""

from __future__ import annotations

import json

import pytest
from sworn_analysis.lib.config import repo_root
from sworn_analysis.lib.evm import (
    ENV_OPCODES,
    analyse,
    env_opcodes,
    function_selectors,
    is_minimal_proxy,
    iter_instructions,
    notable_opcodes,
    strip_metadata,
)

ARTIFACTS = repo_root() / "contracts" / "out" / "StaticAnalysisFixtures.sol"

pytestmark = pytest.mark.skipif(
    not ARTIFACTS.is_dir(), reason="run `forge build` in contracts/ first"
)


def deployed(name: str) -> bytes:
    artifact = json.loads((ARTIFACTS / f"{name}.json").read_text(encoding="utf-8"))
    return bytes.fromhex(artifact["deployedBytecode"]["object"].removeprefix("0x"))


def test_push_immediates_are_not_read_as_opcodes() -> None:
    # 0x3a and 0x41 hidden inside a PUSH32 immediate.
    code = bytes([0x7F]) + bytes([0x3A] * 16 + [0x41] * 16) + bytes([0x00])
    assert env_opcodes(code) == set()


def test_a_real_opcode_outside_push_data_is_found() -> None:
    code = bytes([0x60, 0x01, 0x3A, 0x00])  # PUSH1 0x01; GASPRICE; STOP
    assert env_opcodes(code) == {"GASPRICE"}


def test_instruction_offsets_are_correct() -> None:
    code = bytes([0x60, 0x01, 0x3A, 0x00])
    offsets = [(i.offset, i.opcode) for i in iter_instructions(code)]
    assert offsets == [(0, 0x60), (2, 0x3A), (3, 0x00)]


def test_truncated_push_at_end_of_code_does_not_hang() -> None:
    code = bytes([0x7F, 0x01, 0x02])  # PUSH32 with only 2 bytes left
    assert [i.opcode for i in iter_instructions(code)] == [0x7F]


def test_push0_is_not_treated_as_having_an_immediate() -> None:
    code = bytes([0x5F, 0x3A])  # PUSH0; GASPRICE
    assert env_opcodes(code) == {"GASPRICE"}


def test_contract_with_no_env_reads_is_clean() -> None:
    """The decoy constant makes this the test that catches a naive scanner."""
    code = deployed("NoEnvReads")
    assert env_opcodes(strip_metadata(code)) == set()


def test_gasprice_reader_is_detected() -> None:
    assert "GASPRICE" in env_opcodes(strip_metadata(deployed("ReadsGasPrice")))


def test_multiple_env_reads_are_detected() -> None:
    found = env_opcodes(strip_metadata(deployed("ReadsManyEnv")))
    assert {"GASPRICE", "COINBASE", "BASEFEE", "PREVRANDAO"} <= found


def test_origin_reader_is_detected() -> None:
    assert "ORIGIN" in env_opcodes(strip_metadata(deployed("ReadsOrigin")))


def test_selectors_are_extracted_from_the_dispatcher() -> None:
    # keccak("fee()")[:4] = 0xddca3f43
    assert "0xddca3f43" in function_selectors(strip_metadata(deployed("ReadsGasPrice")))


def test_metadata_trailer_is_stripped() -> None:
    code = deployed("NoEnvReads")
    assert len(strip_metadata(code)) < len(code)


def test_strip_metadata_is_safe_on_short_input() -> None:
    assert strip_metadata(b"") == b""
    assert strip_metadata(b"\x00") == b"\x00"


def test_minimal_proxy_is_recognised() -> None:
    eip1167 = bytes.fromhex(
        "363d3d373d3d3d363d73"
        + "bebebebebebebebebebebebebebebebebebebebe"
        + "5af43d82803e903d91602b57fd5bf3"
    )
    assert is_minimal_proxy(eip1167)
    assert not is_minimal_proxy(deployed("NoEnvReads"))


def test_notable_opcodes_found_in_a_plain_contract() -> None:
    # Solidity's dispatcher does not delegatecall or selfdestruct on its own.
    found = notable_opcodes(strip_metadata(deployed("NoEnvReads")))
    assert "SELFDESTRUCT" not in found
    assert "DELEGATECALL" not in found


def test_analyse_produces_a_stable_report() -> None:
    code = deployed("ReadsManyEnv")
    report = analyse("0x" + "ab" * 20, code)
    assert report.size == len(code)
    assert len(report.sha256) == 64
    assert "GASPRICE" in report.env_opcodes
    assert not report.has_selfdestruct
    # Sorted output keeps snapshots and diffs stable across runs.
    assert report.env_opcodes == sorted(report.env_opcodes)
    assert report.selectors == sorted(report.selectors)


def test_env_opcode_table_covers_the_documented_set() -> None:
    from sworn_analysis.lib.config import load_config

    documented = set(load_config()["metrics"]["env_sensitive"]["env_opcodes"])
    assert documented <= set(ENV_OPCODES.values())
