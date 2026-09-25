"""Event decoding, checked against logs captured from live Base and BNB nodes.

Fixtures are real `PoolManager` logs (`analysis/tests/fixtures/poolmanager_logs.json`),
not hand-written ones: a hand-written fixture only proves the decoder agrees with
whoever wrote the fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sworn_analysis.lib.deployments import INITIALIZE_TOPIC, SWAP_TOPIC
from sworn_analysis.lib.events import (
    DecodeError,
    decode_initialize,
    decode_swap,
)
from sworn_analysis.lib.hookflags import bitmap, touches_swap

FIXTURES = Path(__file__).parent / "fixtures" / "poolmanager_logs.json"
DYNAMIC_FEE_SENTINEL = 0x800000


def _fixtures() -> dict[str, Any]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _all(kind: str) -> list[dict[str, Any]]:
    return [log for chain in _fixtures().values() for log in chain[kind]]


def test_fixtures_are_present_and_from_two_chains() -> None:
    data = _fixtures()
    assert set(data) == {"base", "bnb"}
    assert data["base"]["chain_id"] == 8453
    assert data["bnb"]["chain_id"] == 56


@pytest.mark.parametrize("log", _all("initialize"))
def test_initialize_decodes(log: dict[str, Any]) -> None:
    event = decode_initialize(log)

    assert log["topics"][0].lower() == INITIALIZE_TOPIC
    assert len(event.pool_id) == 66
    assert event.currency0.startswith("0x") and len(event.currency0) == 42
    assert len(event.hooks) == 42
    # v4 requires currency0 < currency1 in the PoolKey ordering.
    assert int(event.currency0, 16) < int(event.currency1, 16)
    assert event.tick_spacing > 0
    assert event.block_number > 0


@pytest.mark.parametrize("log", _all("swap"))
def test_swap_decodes(log: dict[str, Any]) -> None:
    event = decode_swap(log)

    assert log["topics"][0].lower() == SWAP_TOPIC
    assert len(event.sender) == 42
    # One side in, one side out: the signs must oppose on a real swap.
    assert (event.amount0 > 0) != (event.amount1 > 0) or 0 in (event.amount0, event.amount1)
    assert event.sqrt_price_x96 > 0
    assert event.fee >= 0


def test_dynamic_fee_sentinel_is_recognised() -> None:
    events = [decode_initialize(log) for log in _all("initialize")]
    assert all(e.dynamic_fee == (e.fee == DYNAMIC_FEE_SENTINEL) for e in events)
    # The captured window contains both kinds, which is what makes the flag worth testing.
    assert any(e.dynamic_fee for e in events)
    assert any(not e.dynamic_fee for e in events)


def test_hook_addresses_decode_into_plausible_permissions() -> None:
    hooked = [e for e in (decode_initialize(log) for log in _all("initialize")) if not e.hookless]
    assert hooked, "fixture window contained no hooked pools"
    for event in hooked:
        # Every hooked pool's address must carry permission bits; a hook with none would
        # be rejected by PoolManager at initialize time.
        assert bitmap(event.hooks) != 0, event.hooks


def test_most_hooked_pools_touch_the_swap_path() -> None:
    hooked = [e for e in (decode_initialize(log) for log in _all("initialize")) if not e.hookless]
    on_swap = [e for e in hooked if touches_swap(e.hooks)]
    # Not a law, but a strong prior: if this ever drops sharply, the census denominator
    # for the divergence work has changed shape and is worth looking at.
    assert len(on_swap) / len(hooked) > 0.5


def test_pool_ids_are_unique_within_a_chain() -> None:
    for chain, data in _fixtures().items():
        ids = [decode_initialize(log).pool_id for log in data["initialize"]]
        assert len(set(ids)) == len(ids), chain


def test_wrong_topic_is_rejected() -> None:
    log = _all("swap")[0]
    with pytest.raises(DecodeError, match="not an Initialize"):
        decode_initialize(log)


def test_truncated_data_is_rejected() -> None:
    log = dict(_all("initialize")[0])
    log["data"] = log["data"][:100]
    with pytest.raises(DecodeError, match="5 words"):
        decode_initialize(log)


def test_missing_topics_are_rejected() -> None:
    log = dict(_all("initialize")[0])
    log["topics"] = log["topics"][:2]
    with pytest.raises(DecodeError, match="topics"):
        decode_initialize(log)
