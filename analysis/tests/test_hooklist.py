"""The Uniswap hooklist, and what it independently confirms about flag decoding.

v4 derives a hook's permissions from its address. The hooklist records the same
permissions as booleans, produced by Uniswap's own tooling. Comparing the two across
every entry is a far stronger check on `hookflags` than any fixture we could write
ourselves, and if it ever diverges, one of the two is wrong about what a hook can do.
"""

from __future__ import annotations

import pytest
from sworn_analysis.lib.hookflags import ALL_HOOK_MASK, FLAGS, bitmap, returns_delta, touches_swap
from sworn_analysis.lib.hooklist import (
    FLAG_NAME_MAP,
    HooklistEntry,
    by_chain_and_address,
    cache_path,
    load,
)

pytestmark = pytest.mark.skipif(
    not cache_path().is_file(),
    reason="hooklist snapshot not fetched; run scripts/fetch_hooklist.py",
)


@pytest.fixture(scope="module")
def entries() -> list[HooklistEntry]:
    return load()


def test_flag_name_map_covers_every_permission() -> None:
    assert set(FLAG_NAME_MAP.values()) == set(FLAGS)


def test_hooklist_is_substantial(entries: list[HooklistEntry]) -> None:
    assert len(entries) > 1_000


def test_every_address_bitmap_matches_the_registry_flags(entries: list[HooklistEntry]) -> None:
    """The load-bearing check: address bits == declared permissions, for every entry."""
    mismatches = [
        (e.address, e.chain, e.claimed_bitmap, bitmap(e.address))
        for e in entries
        if e.claimed_bitmap != bitmap(e.address)
    ]
    assert not mismatches, f"{len(mismatches)} disagreements, first: {mismatches[:3]}"


def test_bitmaps_stay_inside_the_permission_mask(entries: list[HooklistEntry]) -> None:
    for e in entries:
        assert e.claimed_bitmap & ~ALL_HOOK_MASK == 0, e.address


def test_join_key_is_chain_scoped(entries: list[HooklistEntry]) -> None:
    # The same address is deployed on several chains, so address alone is not a key.
    index = by_chain_and_address(entries)
    assert all(isinstance(k, tuple) and len(k) == 2 for k in index)

    by_address: dict[str, set[int]] = {}
    for chain_id, address in index:
        by_address.setdefault(address, set()).add(chain_id)
    multi_chain = {a: c for a, c in by_address.items() if len(c) > 1}
    assert multi_chain, "expected at least one hook deployed on several chains"


def test_target_chains_are_represented(entries: list[HooklistEntry]) -> None:
    ids = {e.chain_id for e in entries}
    for chain_id in (8453, 1, 130, 56, 42161, 137):
        assert chain_id in ids, f"no hooklist entries for chain {chain_id}"


def test_swap_touching_hooks_decode_consistently(entries: list[HooklistEntry]) -> None:
    for e in entries:
        claims_swap = e.flags.get("beforeSwap", False) or e.flags.get("afterSwap", False)
        claims_delta = e.flags.get("beforeSwapReturnsDelta", False) or e.flags.get(
            "afterSwapReturnsDelta", False
        )
        assert touches_swap(e.address) == claims_swap, e.address
        assert returns_delta(e.address) == claims_delta, e.address


def test_registry_records_no_behaviour(entries: list[HooklistEntry]) -> None:
    """The gap Sworn exists to fill, asserted so it is visible when it closes.

    Every field here is provenance or capability. None of it says whether the hook
    delivers what it quotes, which is why being on this list is not evidence of honesty.
    """
    sample = entries[0]
    recorded = set(vars(sample))
    behavioural = {"divergence_score", "charged_rate", "env_sensitive", "intermittent"}
    assert not (recorded & behavioural), (
        "hooklist now carries behavioural fields. Update docs/STORY.md claim 4 "
        "and the Phase 10 schema PR"
    )
