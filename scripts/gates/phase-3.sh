#!/usr/bin/env bash
# Phase 3 gate: the divergence numbers exist and the engine that produced them is
# calibrated against ground truth.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

PY="$(venv_python)"
CHAIN="${SWORN_CHAIN:-base}"

step "python tests"
(cd analysis && "$PY" -m pytest) || fail "pytest failed"
ok "pipeline tests pass"

step "hookless calibration"
# The load-bearing check. A hookless pool has no hook, so the quote at the pre-fill state
# and the amount delivered must agree. If they do not, the engine is wrong and every
# number below it is worthless. This is why Phase 3 was BLOCKED until it passed.
"$PY" scripts/calibrate_requote.py --chain "$CHAIN" --sample "${SWORN_CALIB_SAMPLE:-10}" \
  || fail "re-quote engine is not calibrated against hookless pools"
ok "hookless pools show no excess take"

step "result files"
for f in divergence.json attribution.json; do
  [ -f "data/results/$f" ] || fail "missing data/results/$f"
done
ok "divergence and attribution produced"

step "schema validation"
"$PY" - <<'PYEOF' || fail "a result file failed schema validation"
import json, sys
sys.path.insert(0, "analysis")
from pathlib import Path
from lib.schema import validate_result, result_files

for path in sorted(Path("data/results").glob("*.json")):
    if path.name not in result_files():
        continue
    validate_result(path.name, json.loads(path.read_text()))
    print(f"    {path.name} ok")
PYEOF
ok "every result file validates"

step "sensitivity sweep is present"
# The headline must not be an artefact of one threshold choice.
"$PY" - <<'PYEOF' || fail "divergence.json has no usable sensitivity sweep"
import json, sys
doc = json.load(open("data/results/divergence.json"))
sweep = doc.get("sensitivity") or []
thresholds = {row["charged_threshold_bps"] for row in sweep}
if len(thresholds) < 2:
    print(f"    only {len(thresholds)} threshold(s) swept")
    sys.exit(1)
published = doc["params"]["charged_threshold_bps"]
if published not in thresholds:
    print(f"    published threshold {published} is not in the sweep {sorted(thresholds)}")
    sys.exit(1)
print(f"    swept thresholds {sorted(thresholds)}, published {published}")
PYEOF
ok "divergent-hook count reported across thresholds"

step "divergence discloses its hookData coverage"
# Hooked re-quotes are made with whatever hookData we could recover. When that is none,
# a hook which prices on hookData is being measured against a call it never received —
# and the result must say so rather than present the number bare.
"$PY" - <<'PYEOF' || fail "divergence.json does not disclose hookData coverage"
import json, sys
doc = json.load(open("data/results/divergence.json"))
hooks = doc.get("hooks") or []
missing = [h["address"] for h in hooks if "hook_data_unknown_share" not in h]
if missing:
    print(f"    {len(missing)} hook(s) do not report hook_data_unknown_share")
    sys.exit(1)
if hooks:
    worst = max(h["hook_data_unknown_share"] for h in hooks)
    print(f"    hookData unknown for up to {worst:.0%} of fills per hook (disclosed)")
PYEOF
ok "hookData coverage is reported alongside every hook"

step "attribution publishes its own coverage"
"$PY" - <<'PYEOF' || fail "attribution.json hides its unlabeled share"
import json, sys
doc = json.load(open("data/results/attribution.json"))
share = doc.get("unlabeled_share")
if share is None:
    print("    no unlabeled_share")
    sys.exit(1)
print(f"    unlabeled share {share:.1%}")
PYEOF
ok "unlabeled share is published, not hidden"

step "no number without a snapshot"
"$PY" - <<'PYEOF' || fail "a result file lacks provenance"
import json, sys
from pathlib import Path
for path in sorted(Path("data/results").glob("*.json")):
    doc = json.loads(path.read_text())
    if not doc.get("meta", {}).get("snapshots"):
        print(f"    {path} has no meta.snapshots")
        sys.exit(1)
PYEOF
ok "every result references the snapshot it came from"
