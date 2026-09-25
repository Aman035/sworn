#!/usr/bin/env bash
# Phase 7 gate: scores are computed, publishable and actually published.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

PY="$(venv_python)"
[ -f .env ] && set -a && . ./.env && set +a

step "HookBook tests"
(cd contracts && forge test --match-contract HookBookTest) || fail "HookBook tests failed"
ok "auth, freshness, signatures and replay protection"

step "flag bits agree across Solidity, config and docs"
(cd analysis && "$PY" -m pytest tests/test_hookbook_flags.py -q) \
  || fail "HookBook flag bits drifted from analysis/config.yaml"
ok "bit positions frozen and consistent"

step "scoring reproduces the documented worked example"
# If the code and docs/METRICS.md ever disagree, a hook developer is being told the wrong
# thing about how to improve their score.
(cd analysis && "$PY" -m pytest tests/test_scoring.py -q) || fail "scoring tests failed"
ok "score, decay and every contribution match METRICS.md"

step "scores.json"
[ -f data/results/scores.json ] || fail "missing data/results/scores.json"
"$PY" - <<'PYEOF' || fail "scores.json is not usable"
import json, sys
sys.path.insert(0, "analysis")
from lib.schema import validate_result

doc = json.load(open("data/results/scores.json"))
validate_result("scores.json", doc)

hooks = doc["hooks"]
scored = [h for h in hooks if h["score"] is not None]
unscored = [h for h in hooks if h["score"] is None]

# Absence of evidence must be reported as absence of evidence. A hook with no score that
# did not also carry INSUFFICIENT_DATA would read on-chain as a clean bill of health.
bad = [h["address"] for h in unscored if not h["insufficient_data"]]
if bad:
    print(f"    {len(bad)} unscored hooks are not flagged INSUFFICIENT_DATA")
    sys.exit(1)

for h in hooks:
    if not h.get("proof", {}).get("snapshot_sha256"):
        print(f"    {h['address']} has no snapshot proof")
        sys.exit(1)

print(f"    {len(hooks):,} hooks: {len(scored):,} scored, {len(unscored):,} insufficient data")
PYEOF
ok "every score carries the snapshot it can be re-derived from"

step "attestor refuses unprovenanced or unmeasured scores"
(cd attestor && ./node_modules/.bin/vitest run --reporter dot) >/dev/null 2>&1 \
  || (cd attestor && ./node_modules/.bin/vitest run) || fail "attestor tests failed"
ok "skips unscored hooks rather than writing them as zero"

step "attestor dry-run against the real scores file"
(cd attestor && ./node_modules/.bin/tsx src/cli.ts --chain base --dry-run --scores ../data/results/scores.json) \
  || fail "attestor dry-run failed"
ok "attestor runs end to end"

step "HookBook is deployed"
ADDR="${HOOKBOOK_ADDRESS_BASE_SEPOLIA:-}"
[ -n "$ADDR" ] || fail "HOOKBOOK_ADDRESS_BASE_SEPOLIA is not set; deploy with script/DeployHookBook.s.sol"
"$PY" - <<PYEOF || fail "deployed HookBook is not usable"
import os, sys
sys.path.insert(0, "analysis")
from lib.rpc import RpcClient
from eth_utils import keccak

addr = "$ADDR"
url = os.environ.get("BASE_SEPOLIA_RPC")
if not url:
    print("    BASE_SEPOLIA_RPC unset")
    sys.exit(1)

def sel(sig):
    return "0x" + keccak(text=sig).hex()[:8]

with RpcClient(url, timeout=30) as rpc:
    code = rpc.call("eth_getCode", [addr, "latest"])
    if code in ("0x", "0x0"):
        print(f"    no code at {addr}")
        sys.exit(1)
    count = int(rpc.call("eth_call", [{"to": addr, "data": sel("attestorCount()")}, "latest"]), 16)
    if count == 0:
        print("    no authorised attestor; the registry cannot be written")
        sys.exit(1)

    # An unscored hook must read as INSUFFICIENT_DATA on-chain, not as a clean zero.
    hook = "0x800cef53c3fd41109dffec62e5251bdd7acba5c7"
    data = sel("flags(address)") + hook[2:].rjust(64, "0")
    flags = int(rpc.call("eth_call", [{"to": addr, "data": data}, "latest"]), 16)
    if flags & (1 << 10) == 0:
        print(f"    unscored hook does not read INSUFFICIENT_DATA (flags={flags})")
        sys.exit(1)
    print(f"    {addr}: {len(code) // 2 - 1} bytes, {count} attestor(s), unscored reads INSUFFICIENT_DATA")
PYEOF
ok "deployed, authorised, and absence reads as absence"
