"""Reconciliation logic: the check that the census is not silently incomplete."""

from __future__ import annotations

import pytest
from sworn_analysis.pipelines.verify_census import Reconciliation, hook_from_data_bytes


def _data(fee: int, tick_spacing: int, hook: str, sqrt_price: int = 1, tick: int = 0) -> str:
    """Build Initialize log data the way the chain does: five 32-byte words."""
    return (
        "0x"
        + f"{fee:064x}"
        + f"{tick_spacing:064x}"
        + hook[2:].rjust(64, "0")
        + f"{sqrt_price:064x}"
        + f"{tick:064x}"
    )


def test_hook_is_read_from_the_third_word() -> None:
    hook = "0x800cef53c3fd41109dffec62e5251bdd7acba5c7"
    assert hook_from_data_bytes(_data(3000, 60, hook)) == hook


def test_hookless_pool_yields_the_zero_address() -> None:
    zero = "0x" + "00" * 20
    assert hook_from_data_bytes(_data(500, 10, zero)) == zero


def test_offset_decode_agrees_with_the_abi_decoder() -> None:
    """The point of the second implementation: it must agree without sharing code."""
    import json
    from pathlib import Path

    from sworn_analysis.lib.events import decode_initialize

    fixtures = Path(__file__).parent / "fixtures" / "poolmanager_logs.json"
    data = json.loads(fixtures.read_text(encoding="utf-8"))
    logs = [log for chain in data.values() for log in chain["initialize"]]
    assert logs

    for log in logs:
        assert hook_from_data_bytes(log["data"]) == decode_initialize(log).hooks


def test_wrong_data_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="160 bytes"):
        hook_from_data_bytes("0x1234")


@pytest.mark.parametrize(
    ("indep", "snap", "expected"),
    [
        (1000, 1000, 0.0),
        (1000, 950, 0.05),
        (1000, 900, 0.10),
        (0, 0, 0.0),
    ],
)
def test_delta_is_relative_to_the_larger_count(indep: int, snap: int, expected: float) -> None:
    r = Reconciliation("base", 10, 1000, indep, snap, indep, snap)
    assert r.pool_delta == pytest.approx(expected)


def test_within_tolerance_passes() -> None:
    r = Reconciliation("base", 40, 80_000, 1000, 960, 200, 195)
    assert r.passed(0.05)


def test_beyond_tolerance_fails() -> None:
    # A pull that skipped a range shows up exactly like this.
    r = Reconciliation("base", 40, 80_000, 1000, 700, 200, 140)
    assert not r.passed(0.05)


def test_hook_and_pool_deltas_are_both_enforced() -> None:
    # Pools agree but hooks do not: a decoding bug rather than a coverage gap.
    r = Reconciliation("base", 40, 80_000, 1000, 1000, 200, 100)
    assert r.pool_delta == 0.0
    assert not r.passed(0.05)
