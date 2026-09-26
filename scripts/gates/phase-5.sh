#!/usr/bin/env bash
# Phase 5 gate: the router is correct at the v4 level and defeats every modelled attack.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

need forge

step "contracts build with the pinned toolchain"
(cd contracts && forge build) || fail "forge build failed"
ok "solc 0.8.26, via-IR, cancun"

step "full test suite"
(cd contracts && forge test) || fail "forge test failed"
ok "unit, fuzz and invariant tests pass"

step "every modelled attack has a test"
missing=""
for t in \
  test_gaspriceSniff_routesToHonest:test_gaspriceSniffHook_losesTheRouteToTheHooklessPool \
  originSniff:test_originSniff_swornRoutesAround \
  coinbaseBasefee:test_coinbaseBasefeeSniff_swornRoutesAround \
  diceRollBlock:test_diceRollBlock_probeSeesTheSameRollAsExecution \
  diceRollCounter:test_diceRollCounter_probeRevertRollsTheCounterBack \
  ownerSwitch:test_ownerSwitch_swornRoutesAroundWhileToxic \
  routerWhitelist:test_routerWhitelist_toxicToSworn_isAvoided \
  gasSniff:test_gasSniff_probeAndExecutionSeeEqualGas \
  callbackSniff:test_callbackSniff_routerLooksIdenticalInBothPhases \
  revertGrief:test_revertGrief_candidateIsSkippedAndTheSwapStillSucceeds \
  gasBurn:test_gasBurn_probeIsBoundedByTheStipend \
  divergence:test_divergenceRevertsWhenAHookBeatsTheProbe ; do
  name="${t#*:}"
  grep -rq "function ${name}(" contracts/test/unit/ || missing="$missing $name"
done
[ -z "$missing" ] || fail "no test for:$missing"
ok "all twelve attacker capabilities from THREAT_MODEL.md are covered"

step "the safety net itself is tested"
# A hook that genuinely beats the probe must cause a revert, not a silent loss. Without
# this the Divergence assertion is untested code on the most important path.
grep -rq "CheatingDivergentHook" contracts/test/fixtures/ \
  || fail "no fixture that defeats the probe, so Divergence is never exercised"
ok "Divergence assertion is exercised by a hook that defeats the probe"

step "coverage on SwornRouter"
PY="$(venv_python)"
(cd contracts && forge coverage --match-path 'test/unit/*' --report lcov --report-file /tmp/sworn-lcov.info >/dev/null 2>&1) \
  || fail "forge coverage failed"
"$PY" - <<'PYEOF' || fail "SwornRouter line coverage below 90%"
import sys
hit = total = 0
inside = False
for line in open("/tmp/sworn-lcov.info"):
    if line.startswith("SF:"):
        inside = "SwornRouter.sol" in line
    elif line.startswith("DA:") and inside:
        _, counts = line.strip().split(":", 1)
        _, count = counts.split(",")
        total += 1
        hit += 1 if int(count) > 0 else 0
    elif line.startswith("end_of_record"):
        inside = False
pct = 100.0 * hit / total if total else 0.0
print(f"    SwornRouter lines {hit}/{total} = {pct:.2f}%")
sys.exit(0 if pct >= 90.0 else 1)
PYEOF
ok "line coverage >= 90%"

step "gas table"
# Deliberately a dedicated benchmark rather than `forge test --gas-report`: gas
# instrumentation interferes with `vm.txGasPrice`, which silently disarms the
# spoofing fixtures: the benchmark would still pass while measuring nothing.
(cd contracts && forge test --match-contract SwornGasTest -vv > /tmp/sworn-gas.txt 2>&1) \
  || fail "gas benchmark failed"
grep -q "overhead vs naive" /tmp/sworn-gas.txt || fail "gas benchmark produced no overhead figures"
sed -n '/baseline (NaiveRouter/,/overhead vs naive/p' /tmp/sworn-gas.txt | sed 's/^/    /' | head -14
ok "probe overhead measured against a slippage-only router"
