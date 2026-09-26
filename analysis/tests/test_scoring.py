"""The divergence score.

The decisive test is that the implementation reproduces the worked example in
`docs/METRICS.md` exactly. If the doc and the code ever disagree, one of them is lying to
a hook developer about how to improve their score.
"""

from __future__ import annotations

import pytest
from sworn_analysis.lib.config import load_config
from sworn_analysis.lib.scoring import (
    ScoreInputs,
    compute_flags,
    decay_factor,
    flag_names,
    flags_word,
    score_hook,
)

# docs/METRICS.md, "Worked example".
WORKED_EXAMPLE = ScoreInputs(
    fills=100,
    charged_rate=0.42,
    median_excess_bps=1800,
    intermittency_crossings=6,
    env_sensitive=True,
    owner_switches=2,
    upgradeable=False,
    revert_asymmetry=0.05,
    days_since_evidence=3,
)


def test_worked_example_from_metrics_doc() -> None:
    result = score_hook(WORKED_EXAMPLE)
    assert result.score == 67
    assert result.decay == pytest.approx(0.8620, abs=1e-4)
    assert sum(result.contributions.values()) == pytest.approx(0.7720, abs=1e-4)


def test_worked_example_contributions_match_the_doc() -> None:
    c = score_hook(WORKED_EXAMPLE).contributions
    assert c["charged_rate"] == pytest.approx(0.2520, abs=1e-4)
    assert c["median_excess"] == pytest.approx(0.2500, abs=1e-4)
    assert c["intermittency"] == pytest.approx(0.0900, abs=1e-4)
    assert c["env_sensitive"] == pytest.approx(0.1500, abs=1e-4)
    assert c["owner_switches"] == pytest.approx(0.0200, abs=1e-4)
    assert c["upgradeable"] == pytest.approx(0.0000, abs=1e-4)
    assert c["revert_gated"] == pytest.approx(0.0100, abs=1e-4)


# ---------------------------------------------------------------------------------------
# absence is not innocence
# ---------------------------------------------------------------------------------------


def test_too_few_fills_scores_none_not_zero() -> None:
    min_fills = load_config()["metrics"]["divergence_score"]["min_fills_for_score"]
    result = score_hook(ScoreInputs(fills=min_fills - 1, charged_rate=1.0, median_excess_bps=5000))

    # A hook could otherwise earn a perfect score by simply not trading.
    assert result.score is None
    assert result.insufficient_data
    assert "INSUFFICIENT_DATA" in result.flag_names


def test_enough_fills_produces_a_number() -> None:
    min_fills = load_config()["metrics"]["divergence_score"]["min_fills_for_score"]
    result = score_hook(ScoreInputs(fills=min_fills, charged_rate=0.0))
    assert result.score == 0
    assert not result.insufficient_data
    assert "INSUFFICIENT_DATA" not in result.flag_names


def test_a_measured_clean_hook_scores_zero() -> None:
    result = score_hook(ScoreInputs(fills=1000))
    assert result.score == 0
    assert result.flags == 0


# ---------------------------------------------------------------------------------------
# bounds and monotonicity
# ---------------------------------------------------------------------------------------


def test_worst_case_saturates_at_100() -> None:
    result = score_hook(
        ScoreInputs(
            fills=10_000,
            charged_rate=1.0,
            median_excess_bps=100_000,
            intermittency_crossings=500,
            env_sensitive=True,
            owner_switches=100,
            upgradeable=True,
            revert_asymmetry=1.0,
            days_since_evidence=0,
        )
    )
    assert result.score == 100


def test_score_is_monotonic_in_charged_rate() -> None:
    def at(rate: float) -> int:
        s = score_hook(ScoreInputs(fills=100, charged_rate=rate)).score
        assert s is not None
        return s

    assert at(0.0) <= at(0.1) <= at(0.25) <= at(0.5) <= at(1.0)


def test_weights_sum_to_one_so_the_scale_is_meaningful() -> None:
    weights = load_config()["metrics"]["divergence_score"]["weights"]
    assert sum(weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------------------
# decay
# ---------------------------------------------------------------------------------------


def test_decay_halves_at_the_half_life() -> None:
    half_life = float(load_config()["metrics"]["divergence_score"]["half_life_days"])
    assert decay_factor(0, half_life) == pytest.approx(1.0)
    assert decay_factor(half_life, half_life) == pytest.approx(0.5)
    assert decay_factor(2 * half_life, half_life) == pytest.approx(0.25)


def test_old_evidence_scores_lower_than_fresh() -> None:
    fresh = score_hook(ScoreInputs(fills=100, charged_rate=0.5, days_since_evidence=0)).score
    stale = score_hook(ScoreInputs(fills=100, charged_rate=0.5, days_since_evidence=60)).score
    assert fresh is not None and stale is not None
    # A hook that stopped charging should improve, but not instantly be pristine.
    assert stale < fresh
    assert stale >= 0


# ---------------------------------------------------------------------------------------
# flags
# ---------------------------------------------------------------------------------------


def test_flags_round_trip() -> None:
    word = flags_word({"DIVERGENT", "ENV_SENSITIVE", "UPGRADEABLE"})
    assert set(flag_names(word)) == {"DIVERGENT", "ENV_SENSITIVE", "UPGRADEABLE"}


def test_unknown_flag_raises() -> None:
    with pytest.raises(KeyError, match="TOTALLY_FINE"):
        flags_word({"TOTALLY_FINE"})


def test_context_flags_carry_no_weight() -> None:
    """Being allowlisted, verified, dynamic-fee or returns-delta is not behaviour.

    These set flags so a reader can see them, but they must not move the score: a hook
    cannot buy a better number by getting listed, and cannot be punished for holding a
    permission it uses honestly.
    """
    plain = score_hook(ScoreInputs(fills=100, charged_rate=0.3))
    decorated = score_hook(
        ScoreInputs(
            fills=100,
            charged_rate=0.3,
            dynamic_fee=True,
            returns_delta=True,
            allowlisted=True,
            verified=True,
        )
    )
    assert plain.score == decorated.score
    assert decorated.flags != plain.flags


def test_compute_flags_sets_owner_switched_only_when_observed() -> None:
    assert "OWNER_SWITCHED" not in flag_names(compute_flags(ScoreInputs(owner_switches=0)))
    assert "OWNER_SWITCHED" in flag_names(compute_flags(ScoreInputs(owner_switches=1)))


def test_flag_word_fits_a_uint32() -> None:
    every = flags_word(set(load_config()["flags"]))
    assert every < 2**32
