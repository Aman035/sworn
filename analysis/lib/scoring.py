"""The divergence score: seven measured inputs, weighted, decayed, clipped to 0-100.

`docs/METRICS.md` defines the formula and carries a worked example; the weights and
normalisation constants live in `analysis/config.yaml`. Nothing here invents a number:
every input comes from a pipeline and every constant comes from config, so a score can be
re-derived by anyone holding the same snapshot.

The one judgement encoded in code rather than config: a hook with too few fills scores
`None`, not zero. Absence of evidence is reported as absence of evidence, because a low
score is only useful to an honest builder if it cannot be obtained by not trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import load_config

_FLAGS: dict[str, int] = {}


def flag_bits() -> dict[str, int]:
    """Bit positions, from config. `HookBook` stores this word verbatim."""
    global _FLAGS
    if not _FLAGS:
        _FLAGS = dict(load_config()["flags"])
    return _FLAGS


def flags_word(names: set[str]) -> int:
    bits = flag_bits()
    word = 0
    for name in sorted(names):
        if name not in bits:
            raise KeyError(f"unknown flag {name!r}; known: {sorted(bits)}")
        word |= 1 << bits[name]
    return word


def flag_names(word: int) -> list[str]:
    return [
        name for name, bit in sorted(flag_bits().items(), key=lambda kv: kv[1]) if word & (1 << bit)
    ]


@dataclass
class ScoreInputs:
    """Everything a score is computed from, for one hook."""

    fills: int = 0
    charged_rate: float = 0.0
    median_excess_bps: float = 0.0
    intermittency_crossings: int = 0
    env_sensitive: bool = False
    owner_switches: int = 0
    upgradeable: bool = False
    revert_asymmetry: float = 0.0
    #: Days since the most recent charged fill; drives the decay term.
    days_since_evidence: float = 0.0
    #: Census-derived context. These set flags but carry no weight: being on a list or
    #: having a permission is not behaviour.
    dynamic_fee: bool = False
    returns_delta: bool = False
    allowlisted: bool = False
    verified: bool = False
    intermittent: bool = False
    divergent: bool = False


@dataclass
class ScoreResult:
    score: int | None
    flags: int
    contributions: dict[str, float] = field(default_factory=dict)
    decay: float = 1.0
    insufficient_data: bool = False

    @property
    def flag_names(self) -> list[str]:
        return flag_names(self.flags)


def _normalise(value: float, full_at: float) -> float:
    """Map a raw input onto [0, 1]; `full_at` is where it saturates."""
    if full_at <= 0:
        return 0.0
    return min(1.0, max(0.0, value / full_at))


def decay_factor(days: float, half_life_days: float) -> float:
    """Evidence ages out.

    A hook that stopped charging a month ago should not score the same as one charging
    today, but it should not immediately score zero either, because the operator can
    turn it back on. Exponential decay is the honest middle.
    """
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (max(0.0, days) / half_life_days)


def compute_flags(inputs: ScoreInputs) -> int:
    names: set[str] = set()
    if inputs.divergent:
        names.add("DIVERGENT")
    if inputs.env_sensitive:
        names.add("ENV_SENSITIVE")
    if inputs.intermittent:
        names.add("INTERMITTENT")
    if inputs.upgradeable:
        names.add("UPGRADEABLE")
    if inputs.owner_switches > 0:
        names.add("OWNER_SWITCHED")
    if inputs.revert_asymmetry > 0:
        names.add("REVERT_GATED")
    if inputs.dynamic_fee:
        names.add("DYNAMIC_FEE")
    if inputs.returns_delta:
        names.add("RETURNS_DELTA")
    if inputs.allowlisted:
        names.add("ALLOWLISTED")
    if inputs.verified:
        names.add("VERIFIED")
    return flags_word(names)


def score_hook(inputs: ScoreInputs) -> ScoreResult:
    """Compute a hook's score, or report that there is not enough evidence to."""
    cfg = load_config()["metrics"]["divergence_score"]
    weights: dict[str, float] = cfg["weights"]
    full_at: dict[str, float] = cfg["full_at"]
    min_fills = int(cfg["min_fills_for_score"])
    half_life = float(cfg["half_life_days"])

    flags = compute_flags(inputs)

    if inputs.fills < min_fills:
        # Not "clean". Unmeasured. The distinction is the whole point of the flag.
        return ScoreResult(
            score=None,
            flags=flags | flags_word({"INSUFFICIENT_DATA"}),
            insufficient_data=True,
        )

    factors = {
        "charged_rate": _normalise(inputs.charged_rate, float(full_at["charged_rate"])),
        "median_excess": _normalise(inputs.median_excess_bps, float(full_at["median_excess_bps"])),
        "intermittency": _normalise(
            inputs.intermittency_crossings, float(full_at["intermittency_crossings"])
        ),
        "env_sensitive": 1.0 if inputs.env_sensitive else 0.0,
        "owner_switches": _normalise(inputs.owner_switches, float(full_at["owner_switches"])),
        "upgradeable": 1.0 if inputs.upgradeable else 0.0,
        "revert_gated": _normalise(inputs.revert_asymmetry, float(full_at["revert_asymmetry"])),
    }

    missing = set(weights) - set(factors)
    if missing:
        raise KeyError(f"config weights have no factor: {sorted(missing)}")

    contributions = {name: factors[name] * weights[name] for name in weights}
    raw = sum(contributions.values())
    decay = decay_factor(inputs.days_since_evidence, half_life)

    score = round(100 * raw * decay)
    score = max(0, min(100, score))

    return ScoreResult(score=score, flags=flags, contributions=contributions, decay=decay)
