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

# Matches the site (app/src/app/globals.css): one near-black instrument ground across
# every page, and one signal colour that means "value a hook took" and nothing else.
PAPER = "#0d1014"
SHEET = "#141a21"
INK = "#f2f4f6"
INK2 = "#9ba5af"
FAINT = "#6c7680"
RULE = "#1e252e"
RULE_HARD = "#2c343e"
SIGNAL = "#f04a10"

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,monospace"
SANS = "'Space Grotesk',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"


def _load(name: str) -> Any:
    path = RESULTS / name
    if not path.is_file():
        raise SystemExit(f"{name} missing — run its pipeline first")
    return json.loads(path.read_text(encoding="utf-8"))


def _frame(width: int, height: int, body: str, title: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{title}">
  <rect width="{width}" height="{height}" rx="10" fill="{PAPER}"/>
{body}
</svg>
"""


def _text(
    x: float,
    y: float,
    s: str,
    *,
    size=13,
    fill=INK,
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


def _box(x, y, w, h, *, stroke=RULE, fill=SHEET, dash="") -> str:
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
    p.append(_text(48, 112, "eth_call — the quote", size=13, family=MONO, fill=INK))
    p.append(_text(48, 140, "tx.gasprice == 0", size=12.5, family=MONO, fill=INK))
    p.append(_text(48, 162, "no state is written", size=12.5, family=MONO, fill=FAINT))
    p.append(_box(48, 182, 260, 56, stroke=INK))
    p.append(
        _text(68, 208, "beforeSwap  →  honest price", size=12.5, family=MONO, fill=INK)
    )
    p.append(_text(68, 226, "the number the user is shown", size=11.5, fill=FAINT))

    # right: the execution
    p.append(_box(372, 84, 300, 176))
    p.append(
        _text(392, 112, "eth_sendRawTransaction", size=13, family=MONO, fill=SIGNAL)
    )
    p.append(_text(392, 140, "tx.gasprice > 0", size=12.5, family=MONO, fill=INK))
    p.append(_text(392, 162, "state is written", size=12.5, family=MONO, fill=FAINT))
    p.append(_box(392, 182, 260, 56, stroke=SIGNAL))
    p.append(
        _text(
            412, 208, "beforeSwap  →  worse price", size=12.5, family=MONO, fill=SIGNAL
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
        ("1", "unlock", "PoolManager hands control back to the router", INK),
        (
            "2",
            "probe each candidate",
            "run the real route, then revert — state and transient storage roll back",
            INK,
        ),
        (
            "3",
            "select",
            "keep the best probed delta and the route that produced it",
            INK,
        ),
        (
            "4",
            "execute",
            "run that route for real, through the same entry point",
            INK,
        ),
        (
            "5",
            "assert",
            "executedDelta == probed[chosen], or the whole transaction reverts",
            SIGNAL,
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
            fill=INK,
        )
    )
    p.append(
        _text(
            28,
            y + 38,
            "makes those two deltas differ, and the trade does not happen at all.",
            size=12.5,
            fill=INK,
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

    row_h, top, left, bar_w = 64, 116, 190, 170
    # Distance from the precision track to the recall track. Both tracks plus their
    # value labels have to finish inside the 700px frame; they did not before.
    gap = 250
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
            left + gap,
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
        p.append(_text(28, y + 8, name, size=13.5, family=MONO, fill=INK))
        note = str(m.get("note", "") or "")
        if note:
            p.append(_text(28, y + 26, note[:40], size=11, fill=FAINT))

        for offset, value in ((0, precision), (gap, recall)):
            x = left + offset
            p.append(
                f'  <rect x="{x}" y="{y - 6}" width="{bar_w}" height="10" rx="5" '
                f'fill="{SHEET}" stroke="{RULE}"/>'
            )
            if value is None:
                p.append(
                    _text(x, y + 22, "not measurable", size=11, family=MONO, fill=FAINT)
                )
                continue
            w = max(2.0, float(value) * bar_w)
            color = SIGNAL if float(value) < 0.5 else INK
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
    if not chains:
        raise SystemExit("census.json has no chains")
    # census.json reports per chain only; the totals row is derived here rather than read,
    # so it cannot disagree with the bars above it.
    totals = {
        "pools_total": sum(int(c["pools_total"]) for c in chains),
        "hooked_pools": sum(int(c["hooked_pools"]) for c in chains),
    }

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

    biggest = max(int(c["pools_total"]) for c in chains) or 1
    y = 104
    for c in sorted(chains, key=lambda c: -int(c["pools_total"])):
        total = int(c["pools_total"])
        hooked = int(c["hooked_pools"])
        # 300px of track, ending well clear of the count that follows it.
        w = max(3.0, total / biggest * 300)
        hw = max(1.0, hooked / biggest * 300)
        p.append(
            _text(28, y + 12, str(c.get("chain", "?")), size=13, family=MONO, fill=INK)
        )
        p.append(
            f'  <rect x="130" y="{y}" width="{w:.1f}" height="16" rx="3" fill="{SHEET}" stroke="{RULE}"/>'
        )
        p.append(
            f'  <rect x="130" y="{y}" width="{hw:.1f}" height="16" rx="3" fill="{INK}"/>'
        )
        share = (hooked / total * 100) if total else 0.0
        p.append(
            _text(
                562,
                y + 13,
                f"{total:,}",
                size=12,
                family=MONO,
                fill=INK,
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
                fill=INK,
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
            f"{totals['pools_total']:,}",
            size=13,
            family=MONO,
            fill=INK,
            anchor="end",
        )
    )
    p.append(
        _text(
            672,
            y + 26,
            # A share, like every row above it: the absolute figure is eight digits wide
            # and ran straight into the pool count beside it.
            f"{totals['hooked_pools'] / totals['pools_total'] * 100:.1f}% hooked",
            size=13,
            family=MONO,
            fill=INK,
            anchor="end",
        )
    )
    return _frame(
        700, y + 52, "\n".join(p), "Pools indexed per chain, and the hooked share"
    )


# ------------------------------------------------------------------------- identity
#
# The mark is `[=]`.
#
# `SwornRouter` reduces to a single assertion — `executedDelta == probed[chosen]` — so the
# logo is that assertion: equality, enforced inside a boundary. The brackets are the
# transaction the probe happens inside; the two bars are the two deltas that have to match.
# It is drawn rather than lettered so it survives being 16px in a browser tab, and it uses
# no colour, because on this project colour means "value a hook took" and a logo has not
# taken anything.


def _mark(size: int = 64, ink: str = INK, stroke: float = 6.2) -> str:
    """The bare `[=]` mark on a transparent ground, sized to a `size` box.

    Proportions are set for the smallest place it appears — a 16px browser tab — so the
    strokes are heavier and the bracket feet shorter than they would be if this were only
    ever going to be seen large.
    """
    k = size / 64.0
    bracket_top, bracket_bottom = 15 * k, 49 * k
    left_x, right_x = 13 * k, 51 * k
    foot = 6 * k
    bar_x1, bar_x2 = 25 * k, 39 * k
    bar_hi, bar_lo = 27.5 * k, 36.5 * k
    w = stroke * k

    return f"""  <g fill="none" stroke="{ink}" stroke-width="{w:.2f}" stroke-linecap="square">
    <path d="M{left_x + foot:.2f} {bracket_top:.2f} H{left_x:.2f} V{bracket_bottom:.2f} H{left_x + foot:.2f}"/>
    <path d="M{right_x - foot:.2f} {bracket_top:.2f} H{right_x:.2f} V{bracket_bottom:.2f} H{right_x - foot:.2f}"/>
    <path d="M{bar_x1:.2f} {bar_hi:.2f} H{bar_x2:.2f}"/>
    <path d="M{bar_x1:.2f} {bar_lo:.2f} H{bar_x2:.2f}"/>
  </g>"""


def logo() -> str:
    """The mark alone, on a transparent ground. For inline use at any size."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="Sworn">
{_mark()}
</svg>
"""


def logo_seal() -> str:
    """The mark reversed out of a filled squircle. For favicons and avatars, where the
    glyph needs a shape of its own to sit in."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="Sworn">
  <rect width="64" height="64" rx="16" fill="{INK}"/>
{_mark(ink=PAPER)}
</svg>
"""


def logo_wordmark() -> str:
    """Mark and wordmark locked up, for a header or a README."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 64" width="300" height="64" role="img" aria-label="Sworn">
  <rect width="64" height="64" rx="16" fill="{INK}"/>
{_mark(ink=PAPER)}
  <text x="82" y="45" font-family="{SANS}" font-size="38" font-weight="700" letter-spacing="-1.4" fill="{INK}">SWORN</text>
</svg>
"""


def banner() -> str:
    """The README's opening image: the lockup, the claim, and the one number."""
    doc = _load("divergence.json")
    w, h = 1200, 320
    p: list[str] = [f'  <rect width="{w}" height="{h}" fill="{PAPER}"/>']

    # No watermark. A cropped glyph at 7% on a near-black ground resolved into stray
    # rectangles rather than into the mark; the lockup carries the identity on its own.

    # The lockup.
    p.append('  <g transform="translate(64 44)">')
    p.append(f'    <rect width="72" height="72" rx="18" fill="{INK}"/>')
    p.append(_mark(size=72, ink=PAPER))
    p.append("  </g>")
    p.append(
        f'  <text x="152" y="98" font-family="{SANS}" font-size="52" font-weight="700" '
        f'letter-spacing="-2" fill="{INK}">SWORN</text>'
    )

    p.append(_text(66, 168, "Execution integrity for Uniswap v4.", size=23, fill=INK))
    p.append(
        _text(
            66,
            202,
            "A hook can quote one price and charge another. This makes it unprofitable.",
            size=17,
            fill=INK2,
        )
    )

    p.append(f'  <line x1="64" y1="238" x2="{w - 64}" y2="238" stroke="{RULE_HARD}"/>')
    n = int(doc["totals"]["divergent_hooks"])
    eligible = int(doc["totals"]["eligible_hooks"])
    p.append(
        _text(
            66,
            270,
            f"{n} of {eligible} measurable hooks on Base charge more than they quote",
            size=15,
            family=MONO,
            fill=SIGNAL,
        )
    )
    p.append(
        _text(
            66,
            294,
            "every figure reproducible from a hashed snapshot",
            size=13,
            family=MONO,
            fill=FAINT,
        )
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Sworn: execution integrity for Uniswap v4">
{chr(10).join(p)}
</svg>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    drawings = {
        "logo.svg": logo,
        "logo-seal.svg": logo_seal,
        "logo-wordmark.svg": logo_wordmark,
        "banner.svg": banner,
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
