#!/usr/bin/env bash
# Phase 8 gate: the SDK builds a call the router accepts, and refuses malformed ones.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

need pnpm

step "typecheck"
pnpm --filter sworn-sdk exec tsc --noEmit -p tsconfig.json || fail "sdk typecheck failed"
ok "strict typecheck passes"

step "sdk tests"
pnpm --filter sworn-sdk test || fail "sdk tests failed"
ok "calldata, validation, scores and policy"

step "sdk builds a publishable package"
pnpm --filter sworn-sdk build || fail "sdk build failed"
for f in sdk/dist/index.js sdk/dist/index.d.ts; do
  [ -f "$f" ] || fail "missing $f"
done
ok "dist and type declarations emitted"

step "calldata matches the router ABI"
# The SDK hand-writes the ABI so it has no build-time dependency on a Foundry artifact.
# That is only safe if the two are checked against each other.
PY="$(venv_python)"
"$PY" - <<'PYEOF' || fail "SDK ABI has drifted from the compiled router"
import json, sys
from pathlib import Path

artifact = json.loads(Path("contracts/out/SwornRouter.sol/SwornRouter.json").read_text())
compiled = {
    (e["name"], tuple(i["type"] for i in e.get("inputs", [])))
    for e in artifact["abi"]
    if e.get("type") == "function"
}

sdk = Path("sdk/src/abi.ts").read_text()
if "swornSwap" not in sdk:
    print("    sdk abi has no swornSwap")
    sys.exit(1)

names = {n for n, _ in compiled}
for required in ("swornSwap", "runRoute", "unlockCallback"):
    if required not in names:
        print(f"    compiled router has no {required}")
        sys.exit(1)

# The tuple shape the SDK encodes must match what the router declares.
swap = next(e for e in artifact["abi"] if e.get("name") == "swornSwap")
params = swap["inputs"][1]["components"]
declared = [c["name"] for c in params]
for field in declared:
    if field not in sdk:
        print(f"    SwornParams.{field} is missing from sdk/src/abi.ts")
        sys.exit(1)
print(f"    SwornParams has {len(declared)} fields, all present in the SDK ABI")
PYEOF
ok "SDK ABI matches the compiled SwornRouter"

step "agent quickstart compiles"
# The quickstart is the first thing an integrator copies. If it does not typecheck against
# a real viem client, the SDK's own client interface is wrong — which is how the loose
# `ReadClient` typing was found.
pnpm --filter sworn-sdk exec tsc --noEmit examples/agent-swap.ts --module esnext \
  --moduleResolution bundler --target es2022 --strict --skipLibCheck \
  || fail "examples/agent-swap.ts does not typecheck against viem"
ok "agent quickstart typechecks against a real viem client"
