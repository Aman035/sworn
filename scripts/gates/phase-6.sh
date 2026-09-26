#!/usr/bin/env bash
# Phase 6 gate: the router works against real chains, and what it is worth is measured.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

need forge
PY="$(venv_python)"

step "fork tests run against real chains"
# Fork tests skip themselves when no archive RPC is configured, which would let this gate
# pass having executed nothing. Require the endpoint rather than accept a silent skip.
[ -f .env ] && set -a && . ./.env && set +a
[ -n "${BASE_RPC_ARCHIVE:-}" ] || fail "BASE_RPC_ARCHIVE is not set; fork tests would skip"
(cd contracts && forge test --match-path 'test/fork/*' -vv > /tmp/sworn-fork.txt 2>&1) \
  || { sed 's/^/    /' /tmp/sworn-fork.txt | tail -30; fail "fork tests failed"; }
grep -qE "[1-9][0-9]* passed" /tmp/sworn-fork.txt || fail "no fork test actually ran"
skipped=$(grep -oE "[0-9]+ skipped" /tmp/sworn-fork.txt | head -1 | cut -d' ' -f1)
ok "fork suite passed (${skipped:-0} skipped for absent pools)"

step "a swap completes end to end through a live mainnet hook"
# The weaker fork tests assert the router never retains value, which a revert satisfies
# too. This phase is only closed by a swap that actually pays out.
grep -q "delivered USDC:" /tmp/sworn-fork.txt \
  || fail "no completed swap through a live hook; RealSwapForkTest did not run"
delivered=$(grep -A1 "delivered USDC:" /tmp/sworn-fork.txt | head -2 | tail -1 | tr -dc '0-9')
[ -n "$delivered" ] && [ "$delivered" -gt 0 ] || fail "live hook swap delivered nothing"
printf '    delivered %s USDC units through a live Base hook\n' "$delivered"
ok "probe, select, execute and assert all hold on mainnet state"

step "replay.json exists and validates"
[ -f data/results/replay.json ] || fail "data/results/replay.json missing; run pipeline E"
"$PY" - <<'PYEOF' || fail "replay.json failed schema validation"
import json, sys
sys.path.insert(0, "analysis")
from sworn_analysis.lib.schema import validate_result
doc = json.load(open("data/results/replay.json"))
validate_result("replay.json", doc)
t = doc["totals"]
print(f"    considered {t['fills_considered']:,}  protected {t['fills_protected']:,}")
print(f"    median protection {t.get('median_protection_bps', 0)} bps")
print(f"    priced share {t.get('price_confidence', 0):.1%}")
PYEOF
ok "protected value is a validated, provenanced result"

step "replay arithmetic is pinned by tests"
(cd analysis && "$PY" -m pytest tests/test_replay.py -q) || fail "replay unit tests failed"
ok "protection, probe gas and pricing refusal are all covered"

step "replay reports its own coverage honestly"
"$PY" - <<'PYEOF' || fail "replay.json hides its pricing coverage"
import json, sys
doc = json.load(open("data/results/replay.json"))
t = doc["totals"]
if "price_confidence" not in t:
    print("    price_confidence absent: a USD total with unknown coverage is not evidence")
    sys.exit(1)
if t.get("protected_usd") is not None and t["price_confidence"] == 0:
    print("    a USD total was published with zero priceable fills")
    sys.exit(1)
PYEOF
ok "every USD figure carries the share of fills it could price"

step "gas table is current"
(cd contracts && forge test --match-contract SwornGasTest -vv > /tmp/sworn-gas.txt 2>&1) \
  || fail "gas benchmark failed"
grep -q "overhead vs naive" /tmp/sworn-gas.txt || fail "gas benchmark produced no figures"
"$PY" - <<'PYEOF' || fail "docs/GAS.md disagrees with the benchmark"
import re, sys
bench = open("/tmp/sworn-gas.txt").read()
doc = open("docs/GAS.md").read()
# The doc quotes measured gas numbers; if the benchmark has moved, the doc is stale.
for n in re.findall(r"swornSwap`, \d candidates?\s*\|\s*([\d,]+)", doc):
    if n.replace(",", "") not in bench.replace(",", ""):
        print(f"    GAS.md quotes {n} which the benchmark no longer produces")
        sys.exit(1)
print("    GAS.md figures all appear in the current benchmark output")
PYEOF
ok "documented overhead matches what the benchmark measures"
