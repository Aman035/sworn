#!/usr/bin/env bash
# Phase 4 gate: the probe kit works and its precision is measured, not assumed.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

PY="$(venv_python)"

step "static analyser tests"
(cd analysis && "$PY" -m pytest tests/test_evm.py -q) || fail "static analyser tests failed"
ok "PUSH immediates are not mistaken for opcodes"

step "detector fixtures compile and are detected"
# The decisive property: a contract whose constant contains 0x3a and 0x41 bytes must not
# be reported as reading tx.gasprice or block.coinbase.
(cd contracts && forge build) || fail "forge build failed"
"$PY" - <<'PYEOF' || fail "static analyser is wrong about a compiled fixture"
import json, sys
sys.path.insert(0, "analysis")
from pathlib import Path
from lib.evm import env_opcodes, strip_metadata
from lib.config import repo_root

out = repo_root() / "contracts" / "out" / "StaticAnalysisFixtures.sol"
def code(name):
    art = json.loads((out / f"{name}.json").read_text())
    return bytes.fromhex(art["deployedBytecode"]["object"].removeprefix("0x"))

clean = env_opcodes(strip_metadata(code("NoEnvReads")))
if clean:
    print(f"    decoy constant misread as env reads: {clean}")
    sys.exit(1)
if "GASPRICE" not in env_opcodes(strip_metadata(code("ReadsGasPrice"))):
    print("    failed to detect a real tx.gasprice read")
    sys.exit(1)
print("    decoy clean, real read detected")
PYEOF
ok "static detection is correct on compiled fixtures"

step "probe results"
[ -f data/results/probe.json ] || fail "missing data/results/probe.json"
"$PY" - <<'PYEOF' || fail "probe.json failed validation"
import json, sys
sys.path.insert(0, "analysis")
from lib.schema import validate_result
doc = json.load(open("data/results/probe.json"))
validate_result("probe.json", doc)
hooks = doc["hooks"]
if not hooks:
    print("    probe.json has no hooks")
    sys.exit(1)
traced = [h for h in hooks if h.get("trace", {}).get("available")]
static = [h for h in hooks if h["static"]["env_opcodes_present"]]
onpath = [h for h in traced if h["trace"]["env_opcodes_on_swap_path"]]
print(f"    {len(hooks)} hooks: static flags {len(static)}, traced {len(traced)}, on-path {len(onpath)}")
# The whole point of trace mode: it must be more selective than static presence.
if traced and len(onpath) > len(static):
    print("    trace flagged more hooks than static presence, which should be impossible")
    sys.exit(1)
PYEOF
ok "probe.json validates and trace is stricter than static presence"

step "precision matrix"
[ -f data/results/precision.json ] || fail "missing data/results/precision.json (needs Phase 3 labels)"
"$PY" - <<'PYEOF' || fail "precision.json is not usable"
import json, sys
sys.path.insert(0, "analysis")
from lib.schema import validate_result
doc = json.load(open("data/results/precision.json"))
validate_result("precision.json", doc)
methods = {m["method"] for m in doc["methods"]}
for required in ("static", "dynamic", "trace", "settled_trade"):
    if required not in methods:
        print(f"    no row for {required}")
        sys.exit(1)
for m in doc["methods"]:
    print(f"    {m['method']:<14} precision={m.get('precision', 0):.2f} recall={m.get('recall', 0):.2f}")
PYEOF
ok "per-method precision and recall reported against settled trades"
