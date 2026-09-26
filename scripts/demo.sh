#!/usr/bin/env bash
# The demo, start to finish. Storyboard in docs/DEMO.md.
#
# Three questions, in the order someone actually asks them:
#
#   1. CAN a hook quote one price and charge another?   a fixture that provably lies
#   2. DOES it happen for real, and can it be stopped?  a live Base hook, forked
#   3. HOW OFTEN?                                       the measurement behind it
#
# It used to be four "acts", which was confusing for two reasons worth recording so
# nobody reintroduces them. Acts 1 and 3 told the same story twice without saying so,
# and the act that only proved "a normal swap still completes" had no payoff to show.
# Worse, `Demo.t.sol` prints its own ACT 1-5 inside part 1, so "act 3" meant two
# different things depending on which output you were reading. Parts here, acts there.
#
# Usage:
#   ./scripts/demo.sh              pause between parts when a terminal is attached
#   ./scripts/demo.sh --no-pause   run straight through, for CI and unattended runs
#   ./scripts/demo.sh --pause      force the pauses on even through a pipe
#   ./scripts/demo.sh --only 2     run one part, for rehearsing a single beat
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$REPO_ROOT"

ANVIL_PORT="${ANVIL_PORT:-8546}"
ANVIL_PID=""
SERVE_PID=""
ONLY=""

cleanup() {
  [ -n "$ANVIL_PID" ] && kill "$ANVIL_PID" 2>/dev/null || true
  [ -n "$SERVE_PID" ] && kill "$SERVE_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Narration pauses. Recording a walkthrough needs room to talk between parts, but this
# script also has to run unattended, so they are on only when someone is plainly
# watching: stdin and stdout both attached to a terminal. SWORN_DEMO_PAUSE=0 or
# --no-pause turns them off; --pause forces them on when output is piped to a recorder.
PAUSE=1
{ [ -t 0 ] && [ -t 1 ]; } || PAUSE=0
[ "${SWORN_DEMO_PAUSE:-1}" = "0" ] && PAUSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-pause) PAUSE=0 ;;
    --pause)    PAUSE=1 ;;
    --only)     shift; ONLY="${1:-}"; [ -n "$ONLY" ] || fail "--only needs a part number" ;;
    --only=*)   ONLY="${1#--only=}" ;;
    -h|--help)  awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *)          fail "unknown option: $1" ;;
  esac
  shift
done

wanted() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

# ------------------------------------------------------------------ presentation helpers

WIDTH=76
rule()  { printf '%s%s%s\n' "$C_DIM" "$(printf '─%.0s' $(seq 1 $WIDTH))" "$C_OFF"; }
heavy() { printf '%s%s%s\n' "$C_DIM" "$(printf '═%.0s' $(seq 1 $WIDTH))" "$C_OFF"; }
say()   { printf '  %s\n' "$*"; }
blank() { printf '\n'; }

# Each part is a question, so the header is the question rather than a label.
part() {
  local n="$1" question="$2" where="$3"
  blank; rule
  printf ' %sPART %s of 3%s  %s\n' "$C_YELLOW" "$n" "$C_OFF" "$question"
  printf ' %s%*s%s\n' "$C_DIM" "$WIDTH" "$where" "$C_OFF"
  rule; blank
}

watch() { printf '  %swatch for:%s %s\n' "$C_DIM" "$C_OFF" "$*"; }

# What the part just did, read back out of the run. A forge dump buries its own
# punchline, and the viewer should never have to find it.
answered() {
  local n="$1"; shift
  _block "$C_GREEN" "PART $n ANSWERED" "$@"
}

# A subordinate result inside a part: an objection closed off, not the part's answer.
# It must not reuse the ANSWERED heading, or a reader counts two answers to one
# question, which is what made the previous act structure confusing.
also() { _block "$C_DIM" "$1" "${@:2}"; }

_block() {
  local colour="$1" label="$2"; shift 2
  local dashes=$((WIDTH - ${#label} - 6))
  blank
  printf '  %s── %s %s%s\n' "$colour" "$label" \
    "$(printf '─%.0s' $(seq 1 $dashes))" "$C_OFF"
  local line
  for line in "$@"; do printf '  %s\n' "$line"; done
  blank
}

# 996999005991991 -> 996,999,005,991,991. Long integers are unreadable on a slide.
group() { printf '%s' "$1" | sed -e :a -e 's/\(.*[0-9]\)\([0-9]\{3\}\)/\1,\2/;ta'; }

# Announce, then wait. The cue prints either way, so the transcript reads the same
# whether or not anyone was there to press a key.
beat() {
  blank
  printf '%s   %s%s\n' "$C_DIM" "$*" "$C_OFF"
  [ "$PAUSE" = "1" ] || return 0
  printf '%s   press enter%s' "$C_DIM" "$C_OFF"
  read -r _ < /dev/tty || true
  blank
}

need forge
[ -f .env ] && set -a && . ./.env && set +a

# ------------------------------------------------------------------------------- opening

blank; heavy
printf ' %sSWORN%s  a hook can quote one price and charge another\n' "$C_YELLOW" "$C_OFF"
heavy; blank

printf '  %sWHAT THIS IS%s\n' "$C_YELLOW" "$C_OFF"
say "Uniswap v4 lets anyone attach code to a pool. That code runs inside the"
say "swap, and it can tell a price quote apart from a real trade, because"
say "tx.gasprice is 0 under eth_call and non-zero in a transaction. So a hook"
say "can promise one number to every quoting engine on the market and pay out"
say "a smaller one to the person actually trading."
blank
say "Sworn is a router that closes that. It re-quotes every candidate route"
say "inside the transaction that settles, takes the best, and reverts if what"
say "executed differs from what it probed."
blank

printf '  %sWHAT THIS DEMO PROVES, IN THREE PARTS%s\n' "$C_YELLOW" "$C_OFF"
blank
printf '  %sPART 1%s  Can a hook do this at all?\n' "$C_YELLOW" "$C_OFF"
say "        A fixture hook, deployed locally, that quotes honestly to a"
say "        simulator and then charges a real transaction."
say "        you will see:  the quote, the payout, and the gap between them"
say "        runs on:       a bare local EVM, no network, ~20 seconds"
blank
printf '  %sPART 2%s  Does it happen for real, and can it be stopped?\n' "$C_YELLOW" "$C_OFF"
say "        A hook that is live on Base right now, at a pinned block, sent"
say "        the identical swap from two different callers."
say "        you will see:  two different payouts for the same trade, and"
say "                       Sworn settling elsewhere for more"
say "        runs on:       Base, forked locally, ~60 seconds"
blank
printf '  %sPART 3%s  How often, and who is exposed?\n' "$C_YELLOW" "$C_OFF"
say "        The measurement the first two parts rest on."
say "        you will see:  how many hooks charge more than they quote, out"
say "                       of those with enough fills to judge, and how many"
say "                       swaps went into them"
say "        runs on:       committed result files, rendered statically"
blank
say "Nothing below is typed in. Every figure is produced during this run, and"
say "the gate greps the source to prove no console.log string contains one."
beat "Starting."

# -------------------------------------------------------------------------------- part 1

if wanted 1; then
  part 1 "Can a hook quote one price and charge another?" "local EVM, nothing forked"
  say "A v4 hook is arbitrary code running inside PoolManager.swap, and it can"
  say "read its environment. tx.gasprice is 0 under eth_call and non-zero in a"
  say "real transaction, so one modifier is enough to answer a quote honestly"
  say "and a trade dishonestly."
  blank
  say "Two pools, same pair. Pool A is hookless. Pool B carries a hook that"
  say "branches on tx.gasprice. Both are deployed into a bare chain seconds"
  say "before the swap, so there is nothing else in play."
  blank
  say "The test prints its own ACT 1 to ACT 5 as it goes. Those are its five"
  say "steps, not the three parts of this script."
  blank
  watch "what pool B quotes, what it delivers, and what Sworn gets instead"
  beat "Running DemoTest."

  DEMO_LOG="$(mktemp)"
  (cd contracts && forge test --match-contract DemoTest -vv) 2>&1 | tee "$DEMO_LOG" \
    || fail "the narrated demo failed; the story is no longer true"

  quoted=$(grep -oE 'pool B quotes: *[0-9]+' "$DEMO_LOG" | grep -oE '[0-9]+$' || true)
  delivered=$(grep -oE 'pool B delivers: *[0-9]+' "$DEMO_LOG" | grep -oE '[0-9]+$' || true)
  taken=$(grep -oE 'quoted \(bps\): *[0-9]+' "$DEMO_LOG" | grep -oE '[0-9]+$' || true)
  regained=$(grep -oE 'recovered \(bps\): *[0-9]+' "$DEMO_LOG" | grep -oE '[0-9]+$' || true)
  rm -f "$DEMO_LOG"

  answered 1 \
    "Yes, a hook can quote one price and charge another." \
    "" \
    "  quoted to a simulator   $(group "$quoted")" \
    "  delivered to a trade    $(group "$delivered")" \
    "" \
    "${taken} bps taken that were never quoted. Every off-chain quoting engine in" \
    "existence would have reported the first number and been right to." \
    "" \
    "Sworn probed both pools inside the transaction that settles, saw the real" \
    "offer rather than the promised one, and routed around it: ${regained} bps recovered."
  ok "a hook can lie, and Sworn routes around it"
fi

# -------------------------------------------------------------------------------- part 2

if wanted 2; then
  if [ -z "${BASE_RPC_ARCHIVE:-}" ]; then
    blank
    warn "BASE_RPC_ARCHIVE not set, so part 2 is skipped."
    say "Set it in .env to run it. Parts 1 and 3 need no network."
  else
    part 2 "Does it happen for real, and can it be stopped?" "Base, forked at a pinned block"
    say "Part 1 used a hook written for the occasion, so the fair objection is"
    say "that the fixture was built to lose. This part uses code nobody in this"
    say "repo wrote, at pinned Base blocks."
    blank
    say "Forking Base locally first. Anvil is a proxy in front of an archive"
    say "node, so the pools, the balances and the hook bytecode are all really"
    say "Base's, at the block we pin."
    beat "Forking Base."

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

    blank
    say "One pool on Base, one block, one swap size. Two callers send the"
    say "identical trade. Neither is known to the hook; both were deployed"
    say "seconds earlier inside the test."
    blank
    watch "the two amounts received, and the gap between them"
    beat "Sending the same swap twice, from two different callers."

    # Through the same local node the fork came up on, so the demo leaves one chain
    # behind for the viewer to poke at. This test pins 51,247,545, well before anvil's
    # own fork block, which works because anvil proxies historical reads upstream.
    BASE_RPC_ARCHIVE="http://127.0.0.1:$ANVIL_PORT" \
      forge test --root contracts --match-path 'test/fork/ProtectedSwap.fork.t.sol' -vv \
      || fail "the mainnet catch did not reproduce"

    read -r c_bps r_bps c_a c_b c_s <<<"$("$(venv_python)" -c 'import json
o = json.load(open("data/results/caught.json"))["observed"]
print(o["charged_extra_bps"], o["recovered_bps"],
      o["caller_a_out"], o["caller_b_out"], o["sworn_settled_out"])')"

    answered 2 \
      "Yes it happens for real, and yes Sworn stops it." \
      "" \
      "  caller A, a naive router   $(group "$c_a")" \
      "  caller B, SwornRouter      $(group "$c_b")" \
      "" \
      "Same pool, same block, same amount in. ${c_bps} bps apart." \
      "" \
      "Sworn does not need to know why it is being charged. It probed, saw the" \
      "real offer, probed the hookless pool beside it, and settled there instead:" \
      "$(group "$c_s"), ${r_bps} bps recovered." \
      "" \
      "Worth sitting with: the offline pipeline in this repo did not flag that" \
      "hook. A re-quote of 10,000 fills missed what one probe caught immediately."
    ok "charged ${c_bps} bps more than another caller; Sworn recovered ${r_bps} bps by routing away"

    # The obvious next objection: a router that reverts on everything would also never
    # be caught overpaying. Answer it here rather than giving it its own part, because
    # "a normal swap still works" is a check, not a beat.
    blank
    say "One more check, because reverting on everything would also pass the"
    say "test above. This asserts the harder thing: a swap through a live hook"
    say "completes, pays out, and passes the divergence check."
    beat "Swapping ETH for USDC through live Base hooks."

    BASE_RPC_ARCHIVE="http://127.0.0.1:$ANVIL_PORT" \
      forge test --root contracts --match-path 'test/fork/RealSwap.fork.t.sol' -vv \
      || fail "real-hook swap failed against the forked chain"
    also "and one more check" \
      "It still trades." \
      "" \
      "Sworn is not a well-defended way of refusing to swap: ETH to USDC" \
      "completed through live Base hooks, probe and execution agreeing."
    ok "ETH -> USDC completed through live Base hooks"
  fi
fi

# -------------------------------------------------------------------------------- part 3

if wanted 3; then
  part 3 "How often, and who is exposed?" "measured, then rendered statically"
  say "Parts 1 and 2 are the mechanism. This is the measurement behind it:"
  say "every v4 pool on four chains, indexed from Initialize logs, and a"
  say "uniform random sample of Base fills each re-quoted against the state"
  say "immediately before it."
  blank
  say "The dashboard is a static export that reads the same data/results/*.json"
  say "the README is generated from, so the two cannot disagree."
  beat "Building the dashboard."

  if [ -d app/node_modules ]; then
    (cd app && npm run build >/dev/null) || fail "dashboard build failed"
    npx --yes serve app/out -l 4321 >/dev/null 2>&1 &
    SERVE_PID=$!
    sleep 3
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:4321/" || echo 000)
    [ "$code" = "200" ] || fail "dashboard did not serve (HTTP $code)"

    read -r n_div n_elig n_into <<<"$("$(venv_python)" -c 'import json
d = json.load(open("data/results/divergence.json"))["totals"]
a = json.load(open("data/results/attribution.json"))["products"]
print(d["divergent_hooks"], d["eligible_hooks"],
      sum(int(p["fills_into_divergent"]) for p in a))')"

    answered 3 \
      "${n_div} of the ${n_elig} hooks with enough fills to classify charge more than they quote," \
      "and $(group "$n_into") swaps on Base went into them." \
      "" \
      "  the argument    http://127.0.0.1:4321" \
      "  the evidence    http://127.0.0.1:4321/evidence/"
    ok "dashboard serving on http://127.0.0.1:4321"
  else
    warn "app/node_modules missing. Run 'cd app && npm install' to include the dashboard"
  fi
fi

# --------------------------------------------------------------------------------- close

blank; heavy
printf ' %sdone%s  every number above was produced by the run, not typed into it\n' \
  "$C_GREEN" "$C_OFF"
heavy

if [ -n "$SERVE_PID" ] || [ -n "$ANVIL_PID" ]; then
  blank
  say "Still up, so you can poke at them:"
  [ -n "$ANVIL_PID" ] && say "  cast block-number --rpc-url http://127.0.0.1:$ANVIL_PORT"
  [ -n "$SERVE_PID" ] && say "  open http://127.0.0.1:4321"
  beat "Press enter to shut them down."
fi
