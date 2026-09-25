#!/usr/bin/env bash
# Phase 0 gate: the toolchain builds, typechecks, tests and lints; the gate runner
# itself refuses to mark a failing phase.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

need forge "install Foundry: https://getfoundry.sh"
need pnpm
need git

step "repo layout"
for d in contracts analysis index probe attestor sdk app data docs scripts; do
  [ -d "$d" ] || fail "missing directory: $d"
done
for f in Makefile PHASES.md .env.example README.md; do
  [ -f "$f" ] || fail "missing file: $f"
done
ok "layout matches SWORN_PLAN.md §1"

step "submodules pinned"
git submodule status --recursive >/dev/null || fail "submodule status failed"
while read -r _sha path _rest; do
  [ -n "$(ls -A "$path" 2>/dev/null)" ] || fail "submodule not checked out: $path"
done < <(git submodule status | sed 's/^[-+U ]//')
ok "v4 dependencies present"

step "forge build"
(cd contracts && forge build) || fail "forge build failed"
ok "contracts compile (solc 0.8.26, via-IR)"

step "forge test"
(cd contracts && forge test) || fail "forge test failed"
ok "solidity tests pass"

step "pnpm typecheck"
pnpm -r --if-present typecheck || fail "typecheck failed"
ok "typescript strict typecheck passes"

step "pnpm test"
pnpm -r --if-present test || fail "workspace tests failed"
ok "workspace tests pass"

step "python tests"
PY="$(venv_python)"
(cd analysis && "$PY" -m pytest) || fail "pytest failed"
"$PY" -m ruff check analysis || fail "ruff failed"
ok "python tests and lint pass"

step "ci workflows"
for wf in ci.yml fork.yml attestor.yml; do
  [ -f ".github/workflows/$wf" ] || fail "missing workflow: .github/workflows/$wf"
done
if command -v actionlint >/dev/null 2>&1; then
  actionlint || fail "actionlint failed"
  ok "actionlint clean"
else
  "$PY" scripts/validate_workflows.py || fail "workflow validation failed"
  warn "actionlint not installed; used the built-in YAML validator instead"
fi

step "gate runner self-test"
./scripts/mark-phase.sh --selftest || fail "mark-phase.sh accepted a failing gate"
ok "mark-phase.sh refuses to mark a failing phase"
