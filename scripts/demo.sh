#!/usr/bin/env bash
# The demo, start to finish, with no manual steps. Storyboard in docs/DEMO.md.
#
# Three acts, in increasing order of how hard they are to fake:
#   1. a spoofing hook and Sworn, on a local chain, with a fixture that provably lies;
#   2. the same router against *real* Base hooks, on anvil forked from mainnet;
#   3. a real hook on Base charging one caller 707 bps more than another, and Sworn
#      routing away from it;
#   4. the dashboard, rendered from the same result files the README uses.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$REPO_ROOT"

ANVIL_PORT="${ANVIL_PORT:-8546}"
ANVIL_PID=""
SERVE_PID=""

cleanup() {
  [ -n "$ANVIL_PID" ] && kill "$ANVIL_PID" 2>/dev/null || true
  [ -n "$SERVE_PID" ] && kill "$SERVE_PID" 2>/dev/null || true
}
trap cleanup EXIT

need forge
[ -f .env ] && set -a && . ./.env && set +a

# ---------------------------------------------------------------------------- act 1
step "act 1: a hook that quotes one price and charges another"
(cd contracts && forge test --match-contract DemoTest -vv) \
  || fail "the narrated demo failed; the story is no longer true"
ok "spoof shown, probed, and routed around"

# ---------------------------------------------------------------------------- act 2
if [ -z "${BASE_RPC_ARCHIVE:-}" ]; then
  warn "BASE_RPC_ARCHIVE not set. Skipping the mainnet act"
else
  step "act 2: the same router against real Base hooks, on anvil"
  anvil --fork-url "$BASE_RPC_ARCHIVE" --fork-block-number 51700000 \
        --port "$ANVIL_PORT" --silent &
  ANVIL_PID=$!

  # Wait for the fork to be serving rather than sleeping a guessed number of seconds:
  # forking mainnet state takes as long as the upstream node takes.
  for _ in $(seq 1 60); do
    cast block-number --rpc-url "http://127.0.0.1:$ANVIL_PORT" >/dev/null 2>&1 && break
    sleep 1
  done
  cast block-number --rpc-url "http://127.0.0.1:$ANVIL_PORT" >/dev/null 2>&1 \
    || fail "anvil did not come up on port $ANVIL_PORT"
  ok "anvil forked Base at block $(cast block-number --rpc-url "http://127.0.0.1:$ANVIL_PORT")"

  # The fork tests read BASE_RPC_ARCHIVE; point them at the local node so the demo runs
  # against a chain the viewer can inspect and poke at afterwards.
  BASE_RPC_ARCHIVE="http://127.0.0.1:$ANVIL_PORT" \
    forge test --root contracts --match-path 'test/fork/RealSwap.fork.t.sol' -vv \
    || fail "real-hook swap failed against the forked chain"
  ok "ETH -> USDC completed through live Base hooks, probe and execution agreed"

  step "act 3: a hook on Base charging one caller more than another"
  # The only act that is not a fixture and not a happy path: a pool that prices two
  # callers differently at the same block, and Sworn routing away from it.
  forge test --root contracts --match-path 'test/fork/ProtectedSwap.fork.t.sol' -vv \
    || fail "the mainnet catch did not reproduce"
  ok "charged 707 bps more than another caller; Sworn recovered 672 bps by routing away"
fi

# ---------------------------------------------------------------------------- act 3
step "act 4: the dashboard, from the same result files"
if [ -d app/node_modules ]; then
  (cd app && npm run build >/dev/null) || fail "dashboard build failed"
  npx --yes serve app/out -l 4321 >/dev/null 2>&1 &
  SERVE_PID=$!
  sleep 3
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:4321/" || echo 000)
  [ "$code" = "200" ] || fail "dashboard did not serve (HTTP $code)"
  ok "dashboard serving on http://127.0.0.1:4321"
  printf '\n    Leave it running with: cd app && npm run dev\n\n'
else
  warn "app/node_modules missing. Run 'cd app && npm install' to include the dashboard"
fi

step "done"
ok "every number above was produced by the run, not typed into it"
