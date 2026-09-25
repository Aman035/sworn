#!/usr/bin/env bash
# Phase 1 gate: the story, the sources and the metric definitions are frozen and
# mechanically consistent with the parameters and the result schema.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

PY="$(venv_python)"

step "required docs exist"
for f in docs/STORY.md docs/SOURCES.md docs/METRICS.md docs/THREAT_MODEL.md docs/ARCHITECTURE.md; do
  [ -s "$f" ] || fail "missing or empty: $f"
done
ok "story, sources, metrics, threat model, architecture"

step "schema is a valid draft 2020-12 document"
"$PY" -c "
from jsonschema import Draft202012Validator
import json, pathlib
Draft202012Validator.check_schema(json.loads(pathlib.Path('analysis/schemas/results.schema.json').read_text()))
print('schema ok')
" || fail "results.schema.json is not a valid JSON Schema"
ok "results.schema.json validates as a schema"

step "docs linter"
"$PY" scripts/lint_docs.py || fail "docs are inconsistent with config.yaml / results.schema.json"
ok "metrics, parameters and result fields agree"

step "python tests"
(cd analysis && "$PY" -m pytest) || fail "pytest failed"
ok "config and schema tests pass"

step "no fabricated numbers yet"
# Until a pipeline writes it, a result file must not exist. This keeps Phase 1 honest:
# the definitions are frozen *before* any number exists.
if compgen -G "data/results/*.json" >/dev/null; then
  fail "data/results/*.json exists before Phase 2; numbers must come from a pipeline"
fi
ok "data/results is empty, as it must be before Phase 2"
