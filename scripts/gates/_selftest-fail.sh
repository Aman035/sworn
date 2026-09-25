#!/usr/bin/env bash
# Deliberately failing gate, used by `mark-phase.sh --selftest` to prove the runner
# never records a DONE entry for a phase whose checks failed.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
fail "this gate always fails (self-test)"
