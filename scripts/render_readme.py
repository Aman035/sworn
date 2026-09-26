"""Render `README.template.md` into `README.md`, substituting real measurements.

Every number in the README must come from `data/results/*.json`. The template carries
placeholders instead of digits:

    {{result:census.json:chains[chain=base].pools_total}}
    {{result:divergence.json:totals.divergent_hooks|int}}

and this script resolves them. `scripts/verify_readme_numbers.py` then checks that the
rendered file contains no numbers the template invented.

Why the indirection: a README is the one file where a stale number is most damaging and
least likely to be noticed. Writing "15.3M pools" by hand means it is wrong the next time
the census runs, and nobody finds out. A placeholder cannot go stale — it either resolves
or the build fails.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "results"
TEMPLATE = ROOT / "README.template.md"
OUTPUT = ROOT / "README.md"

# Whitespace-tolerant on purpose: prettier pads `|` inside markdown table cells, turning
# `{{result:x|int}}` into `{{result:x | int}}`. A stricter pattern silently stopped
# matching and shipped a README full of raw placeholders, because nothing checked for them.
PLACEHOLDER = re.compile(
    r"\{\{\s*result\s*:\s*([^:{}|]+?)\s*:\s*([^|}]+?)\s*(?:\|\s*([a-z_0-9]+)\s*)?\}\}"
)

# Selector inside a list: `chains[chain=base]`
INDEXED = re.compile(r"^([A-Za-z_][\w]*)\[([\w]+)=([^\]]+)\]$")


class RenderError(RuntimeError):
    pass


def _load(filename: str) -> Any:
    path = RESULTS / filename
    if not path.is_file():
        raise RenderError(f"{filename} does not exist — run the pipeline that produces it")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(document: Any, path: str) -> Any:
    node = document
    for segment in path.split("."):
        match = INDEXED.match(segment)
        if match:
            field, key, value = match.groups()
            items = node[field] if isinstance(node, dict) else None
            if not isinstance(items, list):
                raise RenderError(f"{path}: {field} is not a list")
            found = next((i for i in items if str(i.get(key)) == value), None)
            if found is None:
                raise RenderError(f"{path}: no entry with {key}={value}")
            node = found
            continue
        if isinstance(node, dict):
            if segment not in node:
                raise RenderError(f"{path}: no field {segment!r}; have {sorted(node)[:8]}")
            node = node[segment]
        elif isinstance(node, list) and segment.isdigit():
            node = node[int(segment)]
        else:
            raise RenderError(f"{path}: cannot descend into {segment!r}")
    return node


def fmt(value: Any, style: str | None) -> str:
    if style is None:
        return f"{value:,}" if isinstance(value, int) else str(value)
    if style == "int":
        return f"{int(value):,}"
    if style == "raw":
        return str(value)
    if style == "pct":
        return f"{float(value) * 100:.1f}%"
    if style == "pct0":
        return f"{float(value) * 100:.0f}%"
    if style == "bps":
        return f"{float(value):,.0f} bps"
    if style == "f2":
        return f"{float(value):,.2f}"
    if style == "f4":
        return f"{float(value):,.4f}"
    if style == "abs2":
        # For a figure the prose already signs, so the page never reads "$-19.05".
        return f"{abs(float(value)):,.2f}"
    if style == "short":
        n = float(value)
        for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
            if abs(n) >= limit:
                return f"{n / limit:.1f}{suffix}"
        return f"{n:,.0f}"
    raise RenderError(f"unknown format {style!r}")


def render(template: str) -> tuple[str, int]:
    cache: dict[str, Any] = {}
    count = 0

    def substitute(match: re.Match[str]) -> str:
        nonlocal count
        filename, path, style = match.group(1), match.group(2).strip(), match.group(3)
        if filename not in cache:
            cache[filename] = _load(filename)
        count += 1
        return fmt(resolve(cache[filename], path), style)

    return PLACEHOLDER.sub(substitute, template), count


def main() -> int:
    if not TEMPLATE.is_file():
        print(f"no template at {TEMPLATE}", file=sys.stderr)
        return 1
    try:
        rendered, count = render(TEMPLATE.read_text(encoding="utf-8"))
    except RenderError as exc:
        print(f"render failed: {exc}", file=sys.stderr)
        return 1

    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"rendered {count} measurement(s) into {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
