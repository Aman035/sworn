"""Generate the README's diagrams as SVG.

The same rule the README follows applies to its pictures: **no number is typed by hand.**
A chart with a figure baked into it is worse than a stale sentence, because nobody thinks
to re-read a picture. Everything numeric here is read from `data/results/*.json` at build
time, so a chart either reflects the current measurements or the build fails.

The two explanatory diagrams carry no numbers and are laid out here rather than drawn in a
design tool so they stay diffable in review.

Palette matches the dashboard (`app/src/app/globals.css`); each file paints its own
background so it reads correctly under both GitHub themes.

    python scripts/render_graphics.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "results"
OUT = ROOT / "docs" / "assets"

INK = "#0f1419"
SLATE = "#171d26"
RULE = "#232c38"
BRASS = "#e8b84b"
CORAL = "#e5644e"
FAINT = "#5a6675"
PAPER = "#e8ecf1"

MONO = "ui-monospace,'SF Mono','IBM Plex Mono',Menlo,monospace"
SANS = "'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"


def _load(name: str) -> Any:
    path = RESULTS / name
    if not path.is_file():
        raise SystemExit(f"{name} missing — run its pipeline first")
    return json.loads(path.read_text(encoding="utf-8"))


def _frame(width: int, height: int, body: str, title: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{title}">
  <rect width="{width}" height="{height}" rx="10" fill="{INK}"/>
{body}
</svg>
"""


def _text(
    x: float,
    y: float,
    s: str,
    *,
    size=13,
    fill=PAPER,
    family=SANS,
    weight=400,
    anchor="start",
    spacing=0.0,
) -> str:
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    esc = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'  <text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{extra}>{esc}</text>'
    )


def _box(x, y, w, h, *, stroke=RULE, fill=SLATE, dash="") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}"{d}/>'


def _arrow(x1, y1, x2, y2, *, color=FAINT, dash="") -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="1.5" marker-end="url(#a)"{d}/>'
    )


MARKER = f"""  <defs>
    <marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="{FAINT}"/>
    </marker>
  </defs>"""


def attack() -> str:
    """What a quote-spoofing hook does, and why a simulator cannot see it."""
    p: list[str] = [MARKER]
    p.append(
        _text(28, 38, "A hook can answer two different questions", size=17, weight=600)
    )
    p.append(
        _text(
            28,
            60,
            "Both paths run the same contract. Only one of them moves money.",
            size=12.5,
            fill=FAINT,
        )
    )

    # left: the simulation
    p.append(_box(28, 84, 300, 176))
    p.append(_text(48, 112, "eth_call — the quote", size=13, family=MONO, fill=BRASS))
    p.append(_text(48, 140, "tx.gasprice == 0", size=12.5, family=MONO, fill=PAPER))
    p.append(_text(48, 162, "no state is written", size=12.5, family=MONO, fill=FAINT))
    p.append(_box(48, 182, 260, 56, stroke=BRASS))
    p.append(
        _text(
            68, 208, "beforeSwap  →  honest price", size=12.5, family=MONO, fill=BRASS
        )
    )
    p.append(_text(68, 226, "the number the user is shown", size=11.5, fill=FAINT))

    # right: the execution
    p.append(_box(372, 84, 300, 176))
    p.append(
        _text(392, 112, "eth_sendRawTransaction", size=13, family=MONO, fill=CORAL)
    )
    p.append(_text(392, 140, "tx.gasprice > 0", size=12.5, family=MONO, fill=PAPER))
    p.append(_text(392, 162, "state is written", size=12.5, family=MONO, fill=FAINT))
    p.append(_box(392, 182, 260, 56, stroke=CORAL))
    p.append(
        _text(
            412, 208, "beforeSwap  →  worse price", size=12.5, family=MONO, fill=CORAL
        )
    )
    p.append(_text(412, 226, "the number the user receives", size=11.5, fill=FAINT))

    p.append(_arrow(332, 172, 368, 172))
    p.append(_text(350, 162, "", size=11))
    p.append(
        _text(
            28,
            292,
            "The hook reads an environment value that differs between the two, and prices",
            size=12.5,
            fill=FAINT,
        )
    )
    p.append(
        _text(
            28,
            312,
            "accordingly. Nothing in the quote can reveal this: the quote is the honest path.",
            size=12.5,
            fill=FAINT,
        )
    )
    return _frame(
        700,
        340,
        "\n".join(p),
        "How a quote-spoofing hook behaves differently under simulation",
    )


def mechanism() -> str:
    """What SwornRouter does instead."""
    p: list[str] = [MARKER]
    p.append(
        _text(28, 38, "SwornRouter: probe inside the transaction", size=17, weight=600)
    )
    p.append(
        _text(
            28,
            60,
            "No simulation is trusted, because every probe runs where the money does.",
            size=12.5,
            fill=FAINT,
        )
    )

    steps = [
        ("1", "unlock", "PoolManager hands control back to the router", BRASS),
        (
            "2",
            "probe each candidate",
            "run the real route, then revert — state and transient storage roll back",
            BRASS,
        ),
        (
            "3",
            "select",
            "keep the best probed delta and the route that produced it",
            BRASS,
        ),
        (
            "4",
            "execute",
            "run that route for real, through the same entry point",
            BRASS,
        ),
        (
            "5",
            "assert",
            "executedDelta == probed[chosen], or the whole transaction reverts",
            CORAL,
        ),
    ]
    y = 88
    for num, name, why, color in steps:
        p.append(_box(28, y, 644, 50))
        p.append(
            f'  <circle cx="56" cy="{y + 25}" r="13" fill="none" stroke="{color}"/>'
        )
        p.append(
            _text(56, y + 30, num, size=12.5, family=MONO, fill=color, anchor="middle")
        )
        p.append(_text(84, y + 21, name, size=13.5, family=MONO, fill=color))
        p.append(_text(84, y + 39, why, size=12, fill=FAINT))
        y += 60

    p.append(
        _text(
            28,
            y + 18,
            "Step 5 is the guarantee. A hook that quotes one price and executes another",
            size=12.5,
            fill=PAPER,
        )
    )
    p.append(
        _text(
            28,
            y + 38,
            "makes those two deltas differ, and the trade does not happen at all.",
            size=12.5,
            fill=PAPER,
        )
    )
    return _frame(
        700,
        y + 62,
        "\n".join(p),
        "How SwornRouter probes candidates inside the transaction",
    )


def precision_chart() -> str:
    """Precision and recall per detection method, from precision.json."""
    doc = _load("precision.json")
    methods = doc.get("methods", [])
    if not methods:
        raise SystemExit("precision.json has no methods")

    row_h, top, left, bar_w = 64, 116, 232, 300
    height = top + row_h * len(methods) + 52
    p: list[str] = []
    p.append(
        _text(
            28,
            40,
            "Every detector is imprecise, retrospective, or both",
            size=17,
            weight=600,
        )
    )
    p.append(
        _text(
            28,
            62,
            "Ground truth is what hooks did to settled trades. This is the argument for the router.",
            size=12.5,
            fill=FAINT,
        )
    )
    p.append(
        _text(left, 96, "precision", size=11, family=MONO, fill=FAINT, spacing=0.6)
    )
    p.append(
        _text(
            left + bar_w + 56,
            96,
            "recall",
            size=11,
            family=MONO,
            fill=FAINT,
            spacing=0.6,
        )
    )

    for i, m in enumerate(methods):
        y = top + i * row_h
        name = str(m.get("method", "?"))
        precision = m.get("precision")
        recall = m.get("recall")
        p.append(
            f'  <line x1="28" y1="{y - 14}" x2="672" y2="{y - 14}" stroke="{RULE}"/>'
        )
        p.append(_text(28, y + 8, name, size=13.5, family=MONO, fill=PAPER))
        note = str(m.get("note", "") or "")
        if note:
            p.append(_text(28, y + 26, note[:40], size=11, fill=FAINT))

        for offset, value in ((0, precision), (bar_w + 56, recall)):
            x = left + offset
            p.append(
                f'  <rect x="{x}" y="{y - 6}" width="{bar_w - 60}" height="10" rx="5" fill="{SLATE}"/>'
            )
            if value is None:
                p.append(
                    _text(x, y + 22, "not measurable", size=11, family=MONO, fill=FAINT)
                )
                continue
            w = max(2.0, float(value) * (bar_w - 60))
            color = CORAL if float(value) < 0.5 else BRASS
            p.append(
                f'  <rect x="{x}" y="{y - 6}" width="{w:.1f}" height="10" rx="5" fill="{color}"/>'
            )
            p.append(
                _text(
                    x + bar_w - 52,
                    y + 4,
                    f"{float(value) * 100:.0f}%",
                    size=12,
                    family=MONO,
                    fill=color,
                )
            )

    p.append(
        _text(
            28,
            height - 20,
            f"Ground truth: {doc.get('ground_truth', 'settled trades')}",
            size=11.5,
            fill=FAINT,
        )
    )
    return _frame(
        700, height, "\n".join(p), "Precision and recall of each hook detection method"
    )


def census_chart() -> str:
    """Population funnel, from census.json."""
    doc = _load("census.json")
    chains = doc.get("chains", [])
    totals = doc.get("totals", {})

    p: list[str] = []
    p.append(
        _text(28, 40, "The population this is measured against", size=17, weight=600)
    )
    p.append(
        _text(
            28,
            62,
            "Pools indexed from PoolManager Initialize logs, per chain.",
            size=12.5,
            fill=FAINT,
        )
    )

    biggest = max((c.get("pools_total", 0) for c in chains), default=1) or 1
    y = 104
    for c in sorted(chains, key=lambda c: -c.get("pools_total", 0)):
        total = int(c.get("pools_total", 0))
        hooked = int(c.get("pools_hooked", 0))
        w = max(3.0, total / biggest * 420)
        hw = max(1.0, hooked / biggest * 420)
        p.append(
            _text(
                28, y + 12, str(c.get("chain", "?")), size=13, family=MONO, fill=PAPER
            )
        )
        p.append(
            f'  <rect x="130" y="{y}" width="{w:.1f}" height="16" rx="3" fill="{SLATE}" stroke="{RULE}"/>'
        )
        p.append(
            f'  <rect x="130" y="{y}" width="{hw:.1f}" height="16" rx="3" fill="{BRASS}"/>'
        )
        share = (hooked / total * 100) if total else 0.0
        p.append(
            _text(
                562,
                y + 13,
                f"{total:,}",
                size=12,
                family=MONO,
                fill=PAPER,
                anchor="end",
            )
        )
        p.append(
            _text(
                672,
                y + 13,
                f"{share:.1f}% hooked",
                size=12,
                family=MONO,
                fill=BRASS,
                anchor="end",
            )
        )
        y += 34

    y += 8
    p.append(f'  <line x1="28" y1="{y}" x2="672" y2="{y}" stroke="{RULE}"/>')
    p.append(_text(28, y + 26, "total", size=13, family=MONO, fill=FAINT))
    p.append(
        _text(
            562,
            y + 26,
            f"{int(totals.get('pools_total', 0)):,}",
            size=13,
            family=MONO,
            fill=PAPER,
            anchor="end",
        )
    )
    p.append(
        _text(
            672,
            y + 26,
            f"{int(totals.get('pools_hooked', 0)):,} hooked",
            size=13,
            family=MONO,
            fill=BRASS,
            anchor="end",
        )
    )
    return _frame(
        700, y + 52, "\n".join(p), "Pools indexed per chain, and the hooked share"
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    drawings = {
        "attack.svg": attack,
        "mechanism.svg": mechanism,
        "precision.svg": precision_chart,
        "census.svg": census_chart,
    }
    for name, fn in drawings.items():
        (OUT / name).write_text(fn(), encoding="utf-8")
        print(f"  wrote docs/assets/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
