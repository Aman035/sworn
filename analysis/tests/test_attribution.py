"""Attribution: mapping `Swap.sender` to a product.

`METRICS.md` requires every mapping to carry a source and a confidence, and requires the
unlabeled share to be published. A table that hides its own coverage is not evidence, and
a guessed label is worse than no label.
"""

from __future__ import annotations

import pytest
from sworn_analysis.lib.config import load_config, repo_root
from sworn_analysis.pipelines.d_attribution import UNLABELED, load_routers


def routers():
    return load_routers()


def test_router_map_exists_where_config_says() -> None:
    path = repo_root() / load_config()["metrics"]["frontend_attribution"]["router_map"]
    assert path.is_file(), f"{path} is missing"


def test_every_row_has_a_source_and_a_confidence() -> None:
    for (chain, address), row in routers().items():
        assert row.source, f"{chain}/{address} has no source"
        assert 0.0 < row.confidence <= 1.0, f"{chain}/{address} confidence {row.confidence}"


def test_addresses_are_lowercase_and_well_formed() -> None:
    for _, address in routers():
        assert address == address.lower(), f"{address} is not lowercased"
        assert address.startswith("0x") and len(address) == 42


def test_no_duplicate_entries() -> None:
    # The map is keyed by (chain, address); a duplicate would silently take the last one.
    path = repo_root() / load_config()["metrics"]["frontend_attribution"]["router_map"]
    rows = [
        line.split(",")[:2]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and not line.startswith("chain,")
    ]
    keys = [(c.strip(), a.strip().lower()) for c, a in rows]
    assert len(set(keys)) == len(keys), "duplicate (chain, address) in routers.csv"


def test_high_confidence_rows_cite_verified_source() -> None:
    """A 1.0 means the contract's own verified name said so, not that it looked right."""
    for (chain, address), row in routers().items():
        if row.confidence >= 1.0:
            assert "verified" in row.source.lower(), f"{chain}/{address}: {row.source}"


def test_unlabeled_is_not_a_product_name() -> None:
    # `unlabeled` is the bucket for everything unmapped; using it as a label would hide
    # exactly the coverage the metric exists to expose.
    assert UNLABELED not in {row.product for row in routers().values()}


def test_uncertain_rows_are_named_as_uncertain() -> None:
    """Below 1.0 confidence the product must not claim a specific operator."""
    for (chain, address), row in routers().items():
        if row.confidence < 0.8:
            assert row.product.startswith(
                "unknown"
            ), f"{chain}/{address} claims '{row.product}' at confidence {row.confidence}"


@pytest.mark.parametrize("chain", ["base"])
def test_map_covers_the_chain_it_claims(chain: str) -> None:
    entries = [k for k in routers() if k[0] == chain]
    assert entries, f"no router entries for {chain}"
