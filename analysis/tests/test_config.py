"""Phase 0 gate: the config loader works and the chain list matches the plan."""

from __future__ import annotations

import pytest
from sworn_analysis.lib.config import Chain, chain, chains, load_config, path_for

# Priority order is a build decision (Base and BNB first: that is where the named
# 0x hooks live), so it is asserted rather than left to drift.
EXPECTED_PRIORITY = ["base", "bnb", "arbitrum", "unichain", "mainnet", "polygon"]


def test_config_loads() -> None:
    cfg = load_config()
    assert cfg["version"] == 0
    assert set(cfg) >= {"chains", "paths"}


def test_chain_priority_order() -> None:
    ordered = sorted(chains().values(), key=lambda c: c.priority)
    assert [c.name for c in ordered] == EXPECTED_PRIORITY


def test_chain_ids_are_unique_and_correct() -> None:
    ids = {c.name: c.chain_id for c in chains().values()}
    assert ids["base"] == 8453
    assert ids["bnb"] == 56
    assert ids["unichain"] == 130
    assert len(set(ids.values())) == len(ids)


def test_unknown_chain_raises() -> None:
    with pytest.raises(KeyError):
        chain("solana")


def test_rpc_url_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    c: Chain = chain("base")
    monkeypatch.delenv(c.rpc_env, raising=False)
    with pytest.raises(RuntimeError, match=c.rpc_env):
        c.rpc_url()


def test_paths_resolve_under_repo_root() -> None:
    results = path_for("results")
    assert results.name == "results"
    assert (results.parent.parent / "analysis" / "config.yaml").exists()
