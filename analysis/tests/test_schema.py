"""Phase 1 gate support: the schema is well-formed and its field paths resolve."""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from sworn_analysis.lib.schema import (
    load_schema,
    resolve_field,
    result_files,
    validate_result,
)

EXPECTED_FILES = {
    "census.json",
    "divergence.json",
    "intermittency.json",
    "attribution.json",
    "probe.json",
    "precision.json",
    "replay.json",
    "gas.json",
    "scores.json",
    # Beyond the nine the plan named. `caught.json` records one real Base hook pricing two
    # callers differently, observed by a fork test rather than derived from a snapshot, and
    # it is the only figure in the README that comes from the router rather than the
    # measurement pipelines.
    "caught.json",
}

MINIMAL_META = {
    "generated_at": "2026-09-25T00:00:00Z",
    "script_commit": "abcdef1",
    "config_version": 1,
    "snapshots": [{"name": "census-base", "sha256": "0" * 64}],
}


def test_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(load_schema())


def test_declared_result_files_match_the_plan() -> None:
    assert set(result_files()) == EXPECTED_FILES


def test_every_declared_file_has_a_definition() -> None:
    defs = load_schema()["$defs"]
    for filename, ref in result_files().items():
        name = ref.removeprefix("#/$defs/")
        assert name in defs, f"{filename} points at a missing definition {ref}"


@pytest.mark.parametrize(
    "path",
    [
        "divergence.hooks[].charged_rate",
        "divergence.sensitivity[].divergent_hooks",
        "census.chains[].hooks_total",
        "intermittency.hooks[].crossings",
        "attribution.products[].excess_usd",
        "probe.hooks[].env_sensitive",
        "precision.methods[].recall",
        "replay.totals.protected_usd",
        "gas.benchmarks[].overhead_gas",
        "scores.hooks[].score",
    ],
)
def test_field_paths_resolve(path: str) -> None:
    assert isinstance(resolve_field(path), dict)


def test_unknown_field_path_raises_with_context() -> None:
    with pytest.raises(KeyError, match="charged_rat"):
        resolve_field("divergence.hooks[].charged_rat")


def test_validate_result_accepts_a_minimal_document() -> None:
    validate_result("precision.json", {"meta": MINIMAL_META, "methods": []})


def test_validate_result_rejects_a_missing_snapshot() -> None:
    bad = {"meta": {k: v for k, v in MINIMAL_META.items() if k != "snapshots"}, "methods": []}
    with pytest.raises(ValueError, match="snapshots"):
        validate_result("precision.json", bad)


def test_validate_result_rejects_unknown_fields() -> None:
    doc = {"meta": MINIMAL_META, "methods": [], "surprise": 1}
    with pytest.raises(ValueError, match="surprise"):
        validate_result("precision.json", doc)
