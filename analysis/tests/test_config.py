"""Phase 0 gate: the config loader works and the chain list matches the plan."""

from __future__ import annotations

import pytest
from sworn_analysis.lib.config import Chain, chain, chains, load_config, path_for

# Priority order is a build decision (Base and BNB first: that is where the named
# 0x hooks live), so it is asserted rather than left to drift.
EXPECTED_PRIORITY = ["base", "bnb", "arbitrum", "unichain", "mainnet", "polygon"]


def test_config_loads() -> None:
    cfg = load_config()
    assert cfg["version"] >= 1
    assert set(cfg) >= {"chains", "paths", "metrics", "flags"}


def test_score_weights_sum_to_one() -> None:
    weights = load_config()["metrics"]["divergence_score"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_flag_bits_are_unique_and_fit_a_uint32() -> None:
    # HookBook stores this word verbatim, so the bit positions are frozen.
    bits = load_config()["flags"]
    assert len(set(bits.values())) == len(bits)
    assert max(bits.values()) < 32
    assert bits["DIVERGENT"] == 0


def test_charged_threshold_is_in_its_own_sensitivity_sweep() -> None:
    # The headline threshold must be one of the swept values, otherwise the
    # sensitivity table does not actually bracket the published number.
    metrics = load_config()["metrics"]
    assert (
        metrics["charged_fill"]["threshold_bps"]
        in metrics["charged_fill"]["sensitivity_threshold_bps"]
    )
    assert (
        metrics["divergent_hook"]["min_fills"] in metrics["divergent_hook"]["sensitivity_min_fills"]
    )


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
