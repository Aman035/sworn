#!/usr/bin/env bash
#
# Run a phase gate and record the outcome in PHASES.md.
#
#   scripts/mark-phase.sh N                  run gate N; append DONE only if it exits 0
#   scripts/mark-phase.sh N --blocked "why"  record a BLOCKED entry (no gate run)
#   scripts/mark-phase.sh --selftest         prove a failing gate is never marked DONE
#
# The gate is run *by this script*. There is no way to hand it a pre-computed
# "it passed" — that is the whole point of the phase ledger.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
cd "$REPO_ROOT"

LEDGER="$REPO_ROOT/PHASES.md"
LOG_DIR="$REPO_ROOT/docs/phases/gate-logs"

usage() { sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; exit 64; }

# Append one machine-readable row to the ledger table. Rows are never rewritten in
# place: the ledger is an append-only history, so a re-run shows up as a new row.
append_row() {
  local phase="$1" status="$2" commit="$3" gate="$4" evidence="$5"
  local date_utc
  date_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '| %s | %s | %s | `%s` | %s | %s |\n' \
    "$phase" "$status" "$date_utc" "$commit" "$gate" "$evidence" >> "$LEDGER"
}

current_commit() {
  local sha dirty=''
  sha="$(git rev-parse --short HEAD 2>/dev/null || echo 'uncommitted')"
  git diff --quiet 2>/dev/null || dirty='-dirty'
  printf '%s%s' "$sha" "$dirty"
}

run_gate() {
  local phase="$1" script="$2" log="$3"
  set +e
  ( "$script" ) 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  set -e
  return "$rc"
}

# --- self-test -------------------------------------------------------------
# Runs the real marking path against a gate that always fails, and asserts the
# ledger was not touched. Exits 0 when the runner behaved correctly.
if [ "${1:-}" = "--selftest" ]; then
  before="$(sha256sum "$LEDGER" 2>/dev/null || shasum -a 256 "$LEDGER")"
  set +e
  ( "$REPO_ROOT/scripts/gates/_selftest-fail.sh" ) >/dev/null 2>&1
  rc=$?
  set -e
  [ "$rc" -ne 0 ] || { echo "selftest: failing gate exited 0" >&2; exit 1; }
  after="$(sha256sum "$LEDGER" 2>/dev/null || shasum -a 256 "$LEDGER")"
  [ "$before" = "$after" ] || { echo "selftest: ledger was modified by a failing gate" >&2; exit 1; }
  echo "selftest: failing gate exited $rc and left PHASES.md untouched"
  exit 0
fi

PHASE="${1:-}"
[ -n "$PHASE" ] || usage
case "$PHASE" in
  ''|*[!0-9]*) fail "phase must be a number, got '$PHASE'";;
esac

mkdir -p "$LOG_DIR"
[ -f "$LEDGER" ] || fail "missing PHASES.md ledger"

# --- blocked ---------------------------------------------------------------
if [ "${2:-}" = "--blocked" ]; then
  reason="${3:-}"
  [ -n "$reason" ] || fail "--blocked needs a reason"
  append_row "$PHASE" "BLOCKED" "$(current_commit)" "not run" "$reason"
  echo "recorded BLOCKED for phase $PHASE: $reason"
  exit 0
fi

GATE="$REPO_ROOT/scripts/gates/phase-$PHASE.sh"
[ -x "$GATE" ] || fail "no gate script for phase $PHASE ($GATE)"

LOG="$LOG_DIR/phase-$PHASE.log"
echo "running gate for phase $PHASE ..."
if run_gate "$PHASE" "$GATE" "$LOG"; then
  summary="$(grep -c '^  ok' "$LOG" || true)"
  append_row "$PHASE" "DONE" "$(current_commit)" \
    "\`make phase-$PHASE\` — ${summary} checks ok" \
    "[gate log](docs/phases/gate-logs/phase-$PHASE.log), [notes](docs/phases/PHASE-$PHASE.md)"
  printf '\n%sphase %s: DONE%s (recorded in PHASES.md)\n' "$C_GREEN" "$PHASE" "$C_OFF"
else
  rc=$?
  printf '\n%sphase %s: gate failed (exit %s)%s — PHASES.md not modified\n' \
    "$C_RED" "$PHASE" "$rc" "$C_OFF" >&2
  echo "see $LOG" >&2
  exit "$rc"
fi
