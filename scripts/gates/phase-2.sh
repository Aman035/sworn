#!/usr/bin/env bash
# Phase 2 gate: the census exists, decodes correctly, and agrees with an independent count.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

PY="$(venv_python)"
# Chains that must be complete for the gate to pass. Base and BNB carry the story (the
# two hooks 0x named); the rest widen the census and are reported, not required.
REQUIRED_CHAINS="${SWORN_REQUIRED_CHAINS:-base bnb}"

step "python tests"
(cd analysis && "$PY" -m pytest) || fail "pytest failed"
"$PY" -m ruff check analysis scripts || fail "ruff failed"
ok "census, decoding and reconciliation tests pass"

step "flag decoding matches the pinned Hooks.sol"
"$PY" -m pytest analysis/tests/test_hookflags.py -q >/dev/null 2>&1 \
  || (cd analysis && "$PY" -m pytest tests/test_hookflags.py -q) \
  || fail "hook flag decoding does not match v4-core"
ok "address-derived permissions agree with Hooks.sol and all hooklist entries"

step "census snapshots present"
for chain in $REQUIRED_CHAINS; do
  manifest="data/snapshots/census-$chain/MANIFEST.json"
  [ -f "$manifest" ] || fail "no census for $chain (missing $manifest)"
  rows="$("$PY" -c "import json;print(json.load(open('$manifest'))['rows'])")"
  [ "$rows" -gt 0 ] || fail "census for $chain has no rows"
  echo "    $chain: $rows pools"
done
ok "census snapshots exist for: $REQUIRED_CHAINS"

step "snapshot manifests verify"
"$PY" - <<'PY' || fail "snapshot verification failed"
import sys
sys.path.insert(0, "analysis")
import os
from lib.snapshot import verify_snapshot
from pathlib import Path

root = Path("data/snapshots")
problems = []
for d in sorted(root.iterdir()):
    if not (d / "MANIFEST.json").is_file():
        continue
    problems += verify_snapshot(d.name)
for p in problems:
    print(f"    {p}")
sys.exit(1 if problems else 0)
PY
ok "every snapshot file hashes to its manifest"

step "independent reconciliation"
"$PY" -m sworn_analysis.pipelines.verify_census $(for c in $REQUIRED_CHAINS; do printf -- "--chain %s " "$c"; done) \
  || fail "census does not reconcile with an independent count"
ok "census within tolerance of a second, independent implementation"

step "census.json"
[ -f data/results/census.json ] || fail "data/results/census.json not produced"
"$PY" - <<'PY' || fail "census.json failed schema validation"
import json, sys
sys.path.insert(0, "analysis")
from lib.schema import validate_result

doc = json.load(open("data/results/census.json"))
validate_result("census.json", doc)

chains = {c["chain"] for c in doc["chains"]}
required = set(__import__("os").environ.get("SWORN_REQUIRED_CHAINS", "base bnb").split())
missing = required - chains
if missing:
    print(f"    census.json missing chains: {sorted(missing)}")
    sys.exit(1)
if not doc["meta"]["snapshots"]:
    print("    census.json has no snapshot provenance")
    sys.exit(1)
print(f"    {len(doc['chains'])} chain(s), {len(doc['top_hooks'])} top hooks")
PY
ok "census.json validates and carries snapshot provenance"

step "no number without a snapshot"
"$PY" - <<'PY' || fail "a result file lacks snapshot provenance"
import json, sys
from pathlib import Path
for path in sorted(Path("data/results").glob("*.json")):
    doc = json.loads(path.read_text())
    if not doc.get("meta", {}).get("snapshots"):
        print(f"    {path} has no meta.snapshots")
        sys.exit(1)
PY
ok "every result file references the snapshot it came from"
