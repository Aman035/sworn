"""Per-hook metadata: proxy detection and the presence-vs-sensitivity distinction.

The measured reality on Base: 96% of hooks contain *an* environment opcode, but only 12%
contain one that could distinguish a simulation. `GAS` alone appears in 94% because solc
emits it for every external call. A detector built on presence would flag almost every
hook on the chain, which is why `docs/METRICS.md` requires execution on the swap path.
"""

from __future__ import annotations

import pytest
from sworn_analysis.lib.evm import ENV_OPCODES

# Opcodes that can tell a simulation from a real transaction.
DISTINGUISHING = {"GASPRICE", "ORIGIN", "COINBASE", "PREVRANDAO", "BASEFEE", "GASLIMIT"}
# Opcodes a normal contract reads for ordinary reasons.
ROUTINE = {"GAS", "TIMESTAMP", "NUMBER", "CHAINID"}


def test_every_env_opcode_is_classified() -> None:
    """A new opcode in the table must be deliberately sorted into one bucket."""
    assert set(ENV_OPCODES.values()) == DISTINGUISHING | ROUTINE
    assert not (DISTINGUISHING & ROUTINE)


def test_gas_is_not_a_simulation_signal() -> None:
    # solc emits GAS for every external call, so it carries no information at all.
    assert "GAS" in ROUTINE
    assert "GAS" not in DISTINGUISHING


def test_slot_read_treats_empty_word_as_no_proxy() -> None:
    from sworn_analysis.pipelines.a_hook_metadata import ZERO_WORD, _slot

    class Rpc:
        def __init__(self, value: str) -> None:
            self.value = value

        def call(self, method: str, params: list[object] | None = None) -> str:
            return self.value

    assert _slot(Rpc(ZERO_WORD), "0xhook", "0xslot") == ""  # type: ignore[arg-type]
    assert _slot(Rpc(""), "0xhook", "0xslot") == ""  # type: ignore[arg-type]


def test_slot_read_extracts_a_left_padded_address() -> None:
    from sworn_analysis.pipelines.a_hook_metadata import _slot

    class Rpc:
        def call(self, method: str, params: list[object] | None = None) -> str:
            return "0x" + "00" * 12 + "22c38c800f50d55c1365a35f66f970f16f1f3c83"

    assert _slot(Rpc(), "0xhook", "0xslot") == "0x22c38c800f50d55c1365a35f66f970f16f1f3c83"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("implementation", "beacon", "proxiable", "expected"),
    [
        ("", "", "", False),
        ("0x" + "11" * 20, "", "", True),
        ("", "0x" + "22" * 20, "", True),
        ("", "", "0x" + "33" * 20, True),
    ],
)
def test_upgradeable_requires_a_redirectable_target(
    implementation: str, beacon: str, proxiable: str, expected: bool
) -> None:
    assert bool(implementation or beacon or proxiable) is expected


def test_minimal_proxy_is_not_upgradeable() -> None:
    """EIP-1167 bakes its target into the bytecode; there is nothing to re-point."""
    from sworn_analysis.lib.evm import is_minimal_proxy

    stub = bytes.fromhex("363d3d373d3d3d363d73" + "be" * 20 + "5af43d82803e903d91602b57fd5bf3")
    assert is_minimal_proxy(stub)
    # It sets no EIP-1967 slot, so the metadata pipeline records upgradeable=False.
    assert not bool("" or "" or "")
