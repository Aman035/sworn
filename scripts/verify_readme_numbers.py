"""Fail the build if the README contains a number nobody measured.

The rule: every figure in `README.md` comes from `data/results/*.json` via a
`{{result:...}}` placeholder in `README.template.md`. A digit typed directly into the
template is a number with no provenance, and that is exactly the failure mode this whole
repo is built to avoid — it would be a claim about mainnet that nothing can reproduce.

Exempt, because they are not measurements: version numbers, chain ids, contract addresses,
years, list markers, gas constants quoted from the test that produced them, and anything
inside a fenced code block (those are commands and outputs, shown verbatim).

    .venv/bin/python scripts/verify_readme_numbers.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "README.template.md"
RENDERED = ROOT / "README.md"

PLACEHOLDER = re.compile(r"\{\{\s*result\s*:[^}]+\}\}")
CODE_BLOCK = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

# Digits that are not measurements.
ALLOWED = re.compile(
    r"""
    (?:^|(?<=[\s\(\[|]))          # at a boundary
    (?:
        v?\d+\.\d+(?:\.\d+)?      # versions: 0.8.26, v1.2
      | 0x[0-9a-fA-F]+            # hex: addresses, selectors
      | \d{4}                     # years
      | [1-9]\d?\.                # ordered list markers: "1." "12."
      | EIP-\d+                   # standards
      | \#\d+                     # issue numbers
    )
    """,
    re.X,
)

BARE_NUMBER = re.compile(r"(?<![\w.$-])\d[\d,]*(?:\.\d+)?%?")


def strip_exempt(text: str) -> str:
    text = HTML_COMMENT.sub(" ", text)
    text = CODE_BLOCK.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = LINK_TARGET.sub(" ", text)
    text = ALLOWED.sub(" ", text)
    return text


def unmeasured_numbers(template: str) -> list[str]:
    # Placeholders are the sanctioned way to state a number, so remove them first.
    text = PLACEHOLDER.sub(" ", template)
    text = strip_exempt(text)
    return BARE_NUMBER.findall(text)


def main() -> int:
    if not TEMPLATE.is_file():
        print(f"no template at {TEMPLATE}", file=sys.stderr)
        return 1

    template = TEMPLATE.read_text(encoding="utf-8")
    offenders = unmeasured_numbers(template)

    placeholders = PLACEHOLDER.findall(template)
    print(f"  {len(placeholders)} measured value(s) via placeholders")

    if offenders:
        print(f"\n  {len(offenders)} number(s) in README.template.md with no source:", file=sys.stderr)
        for n in sorted(set(offenders)):
            print(f"    {n}", file=sys.stderr)
        print(
            "\n  Replace each with a {{result:file.json:path}} placeholder, or move it "
            "into a code block if it is output rather than a claim.",
            file=sys.stderr,
        )
        return 1

    if not RENDERED.is_file():
        print("  README.md not rendered; run scripts/render_readme.py", file=sys.stderr)
        return 1

    # The rendered file must be current: re-rendering it must change nothing.
    sys.path.insert(0, str(ROOT / "scripts"))
    from render_readme import render

    expected, _ = render(template)
    if expected != RENDERED.read_text(encoding="utf-8"):
        print("  README.md is stale; re-run scripts/render_readme.py", file=sys.stderr)
        return 1

    # An unresolved placeholder is worse than a wrong number: it ships as literal braces
    # in the published README. The staleness check above cannot catch it, because a
    # renderer that fails to match produces the same unresolved text on both sides.
    # Comments are stripped first: the template documents its own syntax in one, and a
    # literal `{{table:...}}` there is documentation, not an unresolved placeholder.
    rendered = HTML_COMMENT.sub(" ", RENDERED.read_text(encoding="utf-8"))
    leftover = re.findall(r"\{\{[^}]*\}\}", rendered)
    if leftover:
        print(f"\n  {len(leftover)} unresolved placeholder(s) in README.md:", file=sys.stderr)
        for item in sorted(set(leftover))[:8]:
            print(f"    {item}", file=sys.stderr)
        print("\n  The renderer did not match them — check the placeholder pattern.", file=sys.stderr)
        return 1

    print("  README.md is current and every number resolves from data/results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
