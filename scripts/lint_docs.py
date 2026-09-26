"""Phase 1 gate: keep the docs, the parameters and the result schema in sync.

Checks, in order:

1. `docs/METRICS.md` and `analysis/config.yaml` describe the same set of metrics.
2. Every metric section names its parameters and its result fields, and every one of
   those resolves, in `config.yaml` by dotted path, in `results.schema.json` by field
   path (`divergence.hooks[].charged_rate`).
3. Every result file declared in the schema is produced by some documented phase.
4. `docs/STORY.md`'s claim table has five rows and no empty cells.
5. `docs/SOURCES.md` gives every source a URL and a date.
6. Mermaid blocks are well-formed (`mmdc` when installed, structural check otherwise).
7. Relative links inside `docs/` and from the repo root resolve to real files.

Run: `.venv/bin/python scripts/lint_docs.py`
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from lib.config import load_config  # noqa: E402
from lib.schema import resolve_field, result_files  # noqa: E402

DOCS = ROOT / "docs"
METRICS_MD = DOCS / "METRICS.md"
STORY_MD = DOCS / "STORY.md"
SOURCES_MD = DOCS / "SOURCES.md"

Errors = list[str]

SECTION_RE = re.compile(r"^### `([a-z0-9_]+)`\s*$", re.MULTILINE)
BOLD_FIELD_RE = re.compile(
    r"^\*\*(Definition|Parameters|Result fields)\.\*\*", re.MULTILINE
)
BACKTICK_RE = re.compile(r"`([^`]+)`")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing required doc: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def split_sections(text: str) -> dict[str, str]:
    """Map metric name -> the body of its `### \\`name\\`` section."""
    matches = list(SECTION_RE.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m.group(1)] = text[m.end() : end]
    return out


def resolve_config_path(dotted: str) -> bool:
    node: Any = load_config()
    for seg in dotted.split("."):
        if not isinstance(node, dict) or seg not in node:
            return False
        node = node[seg]
    return True


def check_metrics() -> Errors:
    errors: Errors = []
    text = read(METRICS_MD)
    sections = split_sections(text)
    configured = set(load_config()["metrics"])

    missing_doc = configured - set(sections)
    missing_cfg = set(sections) - configured
    errors += [
        f"METRICS.md: no section for configured metric `{m}`"
        for m in sorted(missing_doc)
    ]
    errors += [
        f"config.yaml: no `metrics.{m}` for documented metric"
        for m in sorted(missing_cfg)
    ]

    for name, body in sections.items():
        labels = set(BOLD_FIELD_RE.findall(body))
        for required in ("Definition", "Parameters", "Result fields"):
            if required not in labels:
                errors.append(f"METRICS.md `{name}`: missing a **{required}.** line")

        for label, checker, what in (
            ("Parameters", resolve_config_path, "config.yaml"),
            ("Result fields", None, "results.schema.json"),
        ):
            line = extract_line(body, label)
            if line is None:
                continue
            refs = BACKTICK_RE.findall(line)
            if not refs:
                errors.append(f"METRICS.md `{name}`: **{label}.** lists nothing")
            for ref in refs:
                if label == "Parameters":
                    if not resolve_config_path(ref):
                        errors.append(
                            f"METRICS.md `{name}`: `{ref}` not found in {what}"
                        )
                else:
                    try:
                        resolve_field(ref)
                    except KeyError as exc:
                        errors.append(
                            f"METRICS.md `{name}`: `{ref}` not in {what} ({exc})"
                        )
    return errors


def extract_line(body: str, label: str) -> str | None:
    """The full paragraph following `**Label.**`, which may wrap over several lines."""
    marker = f"**{label}.**"
    idx = body.find(marker)
    if idx == -1:
        return None
    rest = body[idx + len(marker) :]
    end = rest.find("\n\n")
    return rest if end == -1 else rest[:end]


def check_result_files_are_documented() -> Errors:
    """Every declared result file must be named somewhere in docs/ or SWORN_PLAN.md."""
    corpus = "\n".join(
        p.read_text(encoding="utf-8")
        for p in [*sorted(DOCS.rglob("*.md")), ROOT / "SWORN_PLAN.md"]
        if p.is_file()
    )
    return [
        f"no doc mentions result file {f}" for f in result_files() if f not in corpus
    ]


def check_story() -> Errors:
    errors: Errors = []
    text = read(STORY_MD)
    rows = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") and not re.match(r"^\s*\|[\s|:-]+\|\s*$", line)
    ]
    if len(rows) < 2:
        return ["STORY.md: no claim table found"]
    header, body = rows[0], rows[1:]
    expected = ["claim", "source", "our artifact", "phase"]
    cols = [c.strip().lower() for c in header.strip().strip("|").split("|")]
    if cols[: len(expected)] != expected:
        errors.append(
            f"STORY.md: claim table header is {cols}, expected {expected} first"
        )
    if len(body) != 5:
        errors.append(
            f"STORY.md: claim table has {len(body)} rows, expected 5 (the five claims)"
        )
    for i, row in enumerate(body, start=1):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        for j, cell in enumerate(cells):
            if not cell:
                errors.append(f"STORY.md: claim row {i} column {j + 1} is empty")
    return errors


def check_sources() -> Errors:
    errors: Errors = []
    text = read(SOURCES_MD)
    blocks = re.split(r"^### ", text, flags=re.MULTILINE)[1:]
    if not blocks:
        return ["SOURCES.md: no `### ` source entries found"]
    for block in blocks:
        title = block.splitlines()[0].strip()
        if "http" not in block:
            errors.append(f"SOURCES.md `{title}`: no URL")
        if not re.search(r"\b(19|20)\d{2}\b", block):
            errors.append(f"SOURCES.md `{title}`: no date")
        if "**Figures we cite.**" not in block:
            errors.append(f"SOURCES.md `{title}`: missing a **Figures we cite.** line")
    return errors


def check_mermaid() -> Errors:
    errors: Errors = []
    blocks: list[tuple[Path, str]] = []
    for md in sorted(DOCS.rglob("*.md")):
        for m in re.finditer(
            r"```mermaid\n(.*?)```", md.read_text(encoding="utf-8"), re.S
        ):
            blocks.append((md, m.group(1)))
    if not blocks:
        return [
            "docs/: no mermaid diagram found (ARCHITECTURE.md needs a data-flow diagram)"
        ]

    mmdc = shutil.which("mmdc")
    for md, src in blocks:
        where = md.relative_to(ROOT)
        if mmdc:
            with tempfile.TemporaryDirectory() as tmp:
                inp = Path(tmp) / "d.mmd"
                inp.write_text(src, encoding="utf-8")
                proc = subprocess.run(
                    [mmdc, "-i", str(inp), "-o", str(Path(tmp) / "d.svg")],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    errors.append(
                        f"{where}: mermaid render failed: {proc.stderr.strip()[:200]}"
                    )
        else:
            errors += structural_mermaid_check(where, src)
    if not mmdc:
        print(
            "  note: mmdc not installed; used the structural mermaid check",
            file=sys.stderr,
        )
    return errors


def structural_mermaid_check(where: Path, src: str) -> Errors:
    """Cheap stand-in for a real render: diagram type, balanced brackets, some edges."""
    errors: Errors = []
    lines = [
        ln.strip()
        for ln in src.splitlines()
        if ln.strip() and not ln.strip().startswith("%%")
    ]
    if not lines:
        return [f"{where}: empty mermaid block"]
    kinds = (
        "graph",
        "flowchart",
        "sequenceDiagram",
        "classDiagram",
        "stateDiagram",
        "erDiagram",
    )
    if not lines[0].startswith(kinds):
        errors.append(
            f"{where}: mermaid block starts with {lines[0]!r}, not a diagram type"
        )
    for ch_open, ch_close in (("[", "]"), ("(", ")"), ("{", "}")):
        if src.count(ch_open) != src.count(ch_close):
            errors.append(f"{where}: unbalanced {ch_open}{ch_close} in mermaid block")
    if lines[0].startswith(("graph", "flowchart")) and not any(
        "-->" in ln or "---" in ln for ln in lines
    ):
        errors.append(f"{where}: flowchart has no edges")
    return errors


def check_links() -> Errors:
    errors: Errors = []
    for md in [*sorted(DOCS.rglob("*.md")), ROOT / "README.md", ROOT / "PHASES.md"]:
        if not md.is_file():
            continue
        for target in LINK_RE.findall(md.read_text(encoding="utf-8")):
            target = target.split("#")[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (md.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{md.relative_to(ROOT)}: broken link -> {target}")
    return errors


def main() -> int:
    checks = (
        ("metrics <-> config <-> schema", check_metrics),
        ("result files documented", check_result_files_are_documented),
        ("story claim table", check_story),
        ("sources", check_sources),
        ("mermaid", check_mermaid),
        ("links", check_links),
    )
    total: Errors = []
    for label, fn in checks:
        errors = fn()
        status = "ok " if not errors else "FAIL"
        print(f"  {status} {label}" + ("" if not errors else f" ({len(errors)})"))
        total += errors

    for err in total:
        print(f"    - {err}", file=sys.stderr)
    if total:
        print(f"\n{len(total)} docs problem(s)", file=sys.stderr)
        return 1
    print("docs are consistent with config.yaml and results.schema.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
