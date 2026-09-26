#!/usr/bin/env bash
# Phase 9 gate: the data and the guarantee are visible, and the demo still tells the truth.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib.sh"
cd "$REPO_ROOT"

need forge
need npm

step "dashboard typechecks and builds"
(cd app && npm run typecheck >/dev/null 2>&1) || fail "app typecheck failed"
(cd app && npm run build >/dev/null 2>&1) || fail "app build failed"
ok "static export produced"

step "every page renders real measurements"
# Deliberately asserted against the built HTML rather than through a browser: the export is
# fully static, so a browser would only confirm that Chrome can display a string already in
# the file. What these tests catch is the failure this dashboard is actually prone to: a
# result file changing shape and every figure silently rendering `undefined` or `NaN` while
# the layout still looks perfect.
(cd app && npx vitest run >/tmp/sworn-app-test.txt 2>&1) \
  || { sed 's/^/    /' /tmp/sworn-app-test.txt | tail -25; fail "dashboard smoke tests failed"; }
grep -oE "Tests +[0-9]+ passed" /tmp/sworn-app-test.txt | head -1 | sed 's/^/    /'
ok "pages carry provenance and no placeholder values"

step "the demo runs end to end, unattended"
[ -x scripts/demo.sh ] || fail "scripts/demo.sh is missing or not executable"
[ -f docs/DEMO.md ] || fail "docs/DEMO.md is missing"
(cd contracts && forge test --match-contract DemoTest -vv > /tmp/sworn-demo.txt 2>&1) \
  || { sed 's/^/    /' /tmp/sworn-demo.txt | tail -25; fail "the narrated demo failed"; }
for beat in "ACT 1" "ACT 2" "ACT 3" "ACT 4" "ACT 5"; do
  grep -q "$beat" /tmp/sworn-demo.txt || fail "demo is missing $beat"
done
ok "all five beats present and passing"

step "the demo's numbers come from the run"
PY="$(venv_python)"
"$PY" - <<'PYEOF' || fail "the demo narrates a number instead of producing one"
import re, sys
src = open("contracts/test/unit/Demo.t.sol").read()
# Every figure must reach the console via a variable, never inside the string literal --
# a demo whose numbers are typed in is a slideshow.
for literal in re.findall(r'console\.log\(\s*"([^"]*)"', src):
    if re.search(r"\d{3,}", literal):
        print(f"    narration contains a figure: {literal!r}")
        sys.exit(1)
print("    no console.log string literal contains a figure")
PYEOF

# And the story must actually hold: the spoof must be visible and Sworn must beat it.
# forge prints the label and the value on one line, so read the number off that line.
taken=$(grep "taken without being quoted" /tmp/sworn-demo.txt | grep -oE '[0-9]+$' | tail -1)
recovered=$(grep "recovered (bps)" /tmp/sworn-demo.txt | grep -oE '[0-9]+$' | tail -1)
[ -n "$taken" ] && [ "$taken" -gt 0 ] || fail "demo showed no spoof"
[ -n "$recovered" ] && [ "$recovered" -gt 0 ] || fail "demo recovered nothing"
printf '    spoof %s bps taken, %s bps recovered by routing around it\n' "$taken" "$recovered"
ok "the guarantee is demonstrated, not asserted"

step "the demo does not overclaim"
grep -q "What the demo does not show" docs/DEMO.md \
  || fail "docs/DEMO.md must state what the demo does not show"
ok "limits stated alongside the walkthrough"
