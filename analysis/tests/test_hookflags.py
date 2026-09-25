"""Phase 2 gate support: address-encoded hook permissions decode correctly."""

from __future__ import annotations

import pytest
from sworn_analysis.lib.hookflags import (
    ALL_HOOK_MASK,
    FLAGS,
    HookFlags,
    InvalidAddressError,
    bitmap,
    flags_from_solidity,
    is_hookless,
    names,
    normalize,
    permissions,
    returns_delta,
    touches_swap,
)

# The two hooks 0x named in their 14 Sep 2026 report. Their low bits are what the
# census must decode, and they are the Phase 3 / Phase 6 fixtures.
ZERO_X_BASE = "0x800cef53c3fd41109dffec62e5251bdd7acba5c7"
ZERO_X_BNB = "0x141984423d1a28242b3dd8888c5b0daa7b13c880"


def test_flag_table_matches_pinned_hooks_sol() -> None:
    # If a v4-core bump renumbers a bit, every hook in the census is mislabelled.
    assert flags_from_solidity() == FLAGS


def test_mask_is_fourteen_bits() -> None:
    assert ALL_HOOK_MASK == 0x3FFF
    assert max(FLAGS.values()) == 1 << 13


def test_zero_address_is_hookless() -> None:
    assert is_hookless("0x" + "0" * 40)
    assert names("0x" + "0" * 40) == []
    assert not touches_swap("0x" + "0" * 40)


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        ("0080", ["BEFORE_SWAP"]),
        ("0040", ["AFTER_SWAP"]),
        ("0088", ["BEFORE_SWAP", "BEFORE_SWAP_RETURNS_DELTA"]),
        ("00c4", ["BEFORE_SWAP", "AFTER_SWAP", "AFTER_SWAP_RETURNS_DELTA"]),
        ("2000", ["BEFORE_INITIALIZE"]),
        ("0001", ["AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA"]),
    ],
)
def test_known_bit_patterns(suffix: str, expected: list[str]) -> None:
    addr = "0x" + "a" * (40 - len(suffix)) + suffix
    assert names(addr) == expected


def test_bitmap_ignores_the_high_bytes() -> None:
    # Only the low 14 bits are permissions; the rest is just a mined address.
    assert bitmap("0x" + "f" * 36 + "0080") == bitmap("0x" + "1" * 36 + "0080")


def test_bitmap_roundtrips_through_names() -> None:
    for addr in (ZERO_X_BASE, ZERO_X_BNB, "0x" + "0" * 36 + "3fff"):
        rebuilt = 0
        for name in names(addr):
            rebuilt |= FLAGS[name]
        assert rebuilt == bitmap(addr)


def test_all_flags_set() -> None:
    addr = "0x" + "0" * 36 + "3fff"
    assert set(names(addr)) == set(FLAGS)
    assert permissions(addr) == dict.fromkeys(FLAGS, True)


def test_named_0x_hooks_decode() -> None:
    """The two hooks 0x named take value in two structurally different ways.

    Base `…a5c7` -> 0x25c7, which includes AFTER_SWAP_RETURNS_DELTA: it can take an
    arbitrary share of the output, matching the reported 18% median take.

    BNB `…c880` -> 0x0880, which is BEFORE_ADD_LIQUIDITY + BEFORE_SWAP and carries *no*
    returns-delta permission: it can only override the fee, matching the reported 0-12.8%
    fee range. So "toxic" is not one permission set, and a census that only counts
    returns-delta hooks would miss this one entirely.
    """
    assert bitmap(ZERO_X_BASE) == 0x25C7
    assert names(ZERO_X_BASE) == [
        "BEFORE_INITIALIZE",
        "AFTER_ADD_LIQUIDITY",
        "AFTER_REMOVE_LIQUIDITY",
        "BEFORE_SWAP",
        "AFTER_SWAP",
        "AFTER_SWAP_RETURNS_DELTA",
        "AFTER_ADD_LIQUIDITY_RETURNS_DELTA",
        "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA",
    ]
    assert returns_delta(ZERO_X_BASE)

    assert bitmap(ZERO_X_BNB) == 0x0880
    assert names(ZERO_X_BNB) == ["BEFORE_ADD_LIQUIDITY", "BEFORE_SWAP"]
    assert not returns_delta(ZERO_X_BNB)

    # Both still run on the swap path, which is the precondition for any take.
    assert touches_swap(ZERO_X_BASE)
    assert touches_swap(ZERO_X_BNB)


def test_returns_delta_requires_a_delta_flag() -> None:
    assert not returns_delta("0x" + "0" * 36 + "00c0")  # before+after swap, no delta
    assert returns_delta("0x" + "0" * 36 + "0088")


def test_normalize_accepts_missing_prefix_and_mixed_case() -> None:
    assert normalize("800CEF53C3FD41109DFFEC62E5251BDD7ACBA5C7") == ZERO_X_BASE


@pytest.mark.parametrize("bad", ["0x123", "not-an-address", "0x" + "g" * 40, ""])
def test_invalid_addresses_raise(bad: str) -> None:
    with pytest.raises(InvalidAddressError):
        bitmap(bad)


def test_dataclass_view_is_frozen_and_complete() -> None:
    f = HookFlags.of(ZERO_X_BASE)
    assert f.address == ZERO_X_BASE
    assert f.bitmap == 0x25C7
    assert f.returns_delta
    with pytest.raises(AttributeError):
        f.bitmap = 1  # type: ignore[misc]
