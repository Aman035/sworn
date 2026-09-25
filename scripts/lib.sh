#!/usr/bin/env bash
# Shared helpers for gate scripts. Sourced, never executed directly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT

# Colours only when attached to a terminal, so CI logs stay clean.
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_RED=''; C_GREEN=''; C_YELLOW=''; C_DIM=''; C_OFF=''
fi

step()  { printf '%s==>%s %s\n' "$C_DIM" "$C_OFF" "$*"; }
ok()    { printf '%s  ok%s  %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn()  { printf '%s warn%s %s\n' "$C_YELLOW" "$C_OFF" "$*"; }
fail()  { printf '%sFAIL%s  %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }

# Fail with a clear message when a required binary is missing, rather than
# letting the gate die on a confusing "command not found".
need() {
  command -v "$1" >/dev/null 2>&1 || fail "required tool '$1' not on PATH${2:+ ($2)}"
}

# The repo pins its Python deps in a local venv; gates must not use a stray system python.
venv_python() {
  local py="$REPO_ROOT/.venv/bin/python"
  [ -x "$py" ] || fail "missing .venv — run 'make install'"
  printf '%s' "$py"
}

# A gate must never be satisfied by an unimplemented phase.
not_implemented() {
  fail "gate for phase $1 is not implemented yet (phase not started)"
}
