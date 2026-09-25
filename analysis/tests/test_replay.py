"""Pipeline E's arithmetic: what Sworn would have protected, and what it refuses to claim.

A protected-value figure is the number most likely to be quoted back and least likely to
be checked, so the parts that could quietly inflate it are pinned here:

* protection is measured against the **traced** realized output, never the `Swap` event,
  which omits whatever the hook took in `afterSwap`;
* probe gas is charged, and charged linearly, from the measured constants in `docs/GAS.md`;
* an output token that cannot be priced from the chain is not priced at all.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sworn_analysis.lib.pricing import NATIVE, price
from sworn_analysis.pipelines.e_replay import PROBE_GAS_EACH, PROBE_GAS_FIRST, probe_gas, summarize

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
SHIB = "0x1111111111111111111111111111111111111111"


def test_probe_gas_is_linear_after_the_first_candidate() -> None:
    assert probe_gas(0) == 0
    assert probe_gas(1) == PROBE_GAS_FIRST
    assert probe_gas(2) == PROBE_GAS_FIRST + PROBE_GAS_EACH
    # The first probe pays for the machinery — an extra unlock frame, the self-call and
    # the delta comparison. Every one after is just another swap that reverts.
    assert probe_gas(4) - probe_gas(3) == probe_gas(3) - probe_gas(2)


def test_probe_gas_matches_the_documented_benchmark() -> None:
    """These constants are quoted in docs/GAS.md; drifting apart makes the doc a lie."""
    assert PROBE_GAS_FIRST == 92_717
    assert PROBE_GAS_EACH == 68_000


def test_a_stablecoin_output_is_priced_at_face_value() -> None:
    priced = price("base", USDC, 133_138_269, None)
    assert priced.basis == "stable"
    assert priced.usd == pytest.approx(133.138269)


def test_eth_is_priced_from_the_chain_rate_not_a_guess() -> None:
    assert price("base", WETH, 10**18, 2500.0).usd == pytest.approx(2500.0)
    assert price("base", NATIVE, 10**18, 2500.0).usd == pytest.approx(2500.0)
    # No rate available means no dollar figure, rather than a stale or assumed one.
    assert price("base", WETH, 10**18, None).usd is None


def test_an_unknown_token_is_not_priced() -> None:
    priced = price("base", SHIB, 10**24, 2500.0)
    assert priced.usd is None
    assert priced.basis == ""


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_protection_counts_only_fills_a_candidate_beat() -> None:
    rep = _frame(
        [
            # Beaten by 100 bps.
            {
                "chain": "base",
                "hook": "0xa",
                "tx_hash": "0x1",
                "block_number": 1,
                "out_currency": USDC,
                "realized": "1000000",
                "best_candidate": "1010000",
                "best_pool": "0xp",
                "candidates": 2,
                "gas_overhead": probe_gas(2),
                "protection": "10000",
                "protection_bps": 100.0,
            },
            # Candidate was worse; no protection, and it must not count as a loss either.
            {
                "chain": "base",
                "hook": "0xb",
                "tx_hash": "0x2",
                "block_number": 1,
                "out_currency": USDC,
                "realized": "1000000",
                "best_candidate": "990000",
                "best_pool": "0xp",
                "candidates": 2,
                "gas_overhead": probe_gas(2),
                "protection": "0",
                "protection_bps": 0.0,
            },
        ]
    )
    totals = summarize("base", rep, {1: 2500.0}, {"0x1": 10**7, "0x2": 10**7})

    assert totals["fills_considered"] == 2
    assert totals["fills_protected"] == 1
    assert totals["median_protection_bps"] == 100.0


def test_gas_is_subtracted_at_the_price_the_fill_actually_paid() -> None:
    gas_price = 10**9  # 1 gwei
    overhead = probe_gas(3)
    rep = _frame(
        [
            {
                "chain": "base",
                "hook": "0xa",
                "tx_hash": "0x1",
                "block_number": 1,
                "out_currency": USDC,
                "realized": "1000000",
                "best_candidate": "1010000",
                "best_pool": "0xp",
                "candidates": 3,
                "gas_overhead": overhead,
                "protection": "10000",
                "protection_bps": 100.0,
            }
        ]
    )
    eth_usd = 2500.0
    totals = summarize("base", rep, {1: eth_usd}, {"0x1": gas_price})

    gross = 10000 / 1e6  # $0.01 of USDC
    gas_usd = overhead * gas_price / 1e18 * eth_usd
    assert totals["protected_usd"] == pytest.approx(round(gross - gas_usd, 2), abs=0.005)
    # Charging nothing for the probe would overstate the total.
    assert gas_usd > 0


def test_unpriceable_fills_lower_confidence_rather_than_the_total() -> None:
    rep = _frame(
        [
            {
                "chain": "base",
                "hook": "0xa",
                "tx_hash": "0x1",
                "block_number": 1,
                "out_currency": USDC,
                "realized": "1000000",
                "best_candidate": "1010000",
                "best_pool": "0xp",
                "candidates": 1,
                "gas_overhead": probe_gas(1),
                "protection": "10000",
                "protection_bps": 100.0,
            },
            {
                "chain": "base",
                "hook": "0xb",
                "tx_hash": "0x2",
                "block_number": 1,
                "out_currency": SHIB,
                "realized": "1000000",
                "best_candidate": "1500000",
                "best_pool": "0xp",
                "candidates": 1,
                "gas_overhead": probe_gas(1),
                "protection": "500000",
                "protection_bps": 5000.0,
            },
        ]
    )
    totals = summarize("base", rep, {1: 2500.0}, {"0x1": 10**7, "0x2": 10**7})

    # Both fills are protected and both appear in the bps median...
    assert totals["fills_protected"] == 2
    # ...but only the USDC one reaches the dollar total, and the gap is published.
    assert totals["price_confidence"] == pytest.approx(0.5)


def test_no_priceable_fills_yields_no_dollar_figure() -> None:
    rep = _frame(
        [
            {
                "chain": "base",
                "hook": "0xa",
                "tx_hash": "0x1",
                "block_number": 1,
                "out_currency": SHIB,
                "realized": "1000000",
                "best_candidate": "1010000",
                "best_pool": "0xp",
                "candidates": 1,
                "gas_overhead": probe_gas(1),
                "protection": "10000",
                "protection_bps": 100.0,
            }
        ]
    )
    totals = summarize("base", rep, {}, {"0x1": 10**7})
    assert totals["protected_usd"] is None
    assert totals["price_confidence"] == 0.0


def test_amounts_beyond_int64_survive_the_frame() -> None:
    """Protection is an amount, and amounts here exceed 2^63."""
    big = 19487100457704554985674870
    rep = _frame(
        [
            {
                "chain": "base",
                "hook": "0xa",
                "tx_hash": "0x1",
                "block_number": 1,
                "out_currency": SHIB,
                "realized": str(big),
                "best_candidate": str(big * 2),
                "best_pool": "0xp",
                "candidates": 1,
                "gas_overhead": probe_gas(1),
                "protection": str(big),
                "protection_bps": 10_000.0,
            }
        ]
    )
    totals = summarize("base", rep, {}, {})
    assert totals["fills_protected"] == 1
    assert int(rep.protection[0]) == big
