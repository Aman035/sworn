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

# The logo does not follow the theme. Palette tokens flipped once already when the site
# went dark, which silently inverted the mark into light-on-light; an identity has to be
# fixed regardless of what the product's surfaces are doing.
LOGO_DARK = "#101418"
LOGO_LIGHT = "#f4f6f7"

MONO = "ui-monospace,'JetBrains Mono','SF Mono',Menlo,monospace"
SANS = "'Space Grotesk',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"


def _load(name: str) -> Any:
    path = RESULTS / name
    if not path.is_file():
        raise SystemExit(f"{name} missing. Run its pipeline first")
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
    p.append(_text(48, 112, "eth_call: the quote", size=13, family=MONO, fill=INK))
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
            "run the real route, then revert. State and transient storage roll back",
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


def routing() -> str:
    """Two lanes, side by side: how a router works today, and how Sworn works.

    The whole argument is a change in *when* the quote happens, which is hard to see in
    prose and obvious once the two call sequences sit next to each other. The left lane
    crosses a boundary between two transactions, and the hook answers differently on
    either side of it. The right lane never leaves one transaction.
    """
    p: list[str] = [MARKER]
    lane = 420
    left = 28
    right = left + lane + 44
    w = right + lane + 60
    y0, row, box = 132, 68, 46

    p.append(_text(left, 36, "Where the quote happens", size=17, weight=600))
    p.append(
        _text(
            left,
            58,
            "A quote and a trade are two different calls today. Sworn makes them one.",
            size=12.5,
            fill=FAINT,
        )
    )

    for x, title, sub, colour in (
        (left, "Today", "quote off-chain, execute on-chain", FAINT),
        (right, "With Sworn", "quote and execute in one transaction", SIGNAL),
    ):
        p.append(_text(x, 92, title, size=14, family=MONO, fill=colour, weight=600))
        p.append(_text(x, 110, sub, size=11.5, fill=FAINT))

    # (label, caption, is the step where the harm lands)
    today = [
        ("eth_call to the hook", "the router asks for a price", False),
        ("hook answers honestly", "quotes 100, because nothing is at stake", False),
        ("router builds the trade", "on a promise it cannot enforce", False),
        ("the transaction lands", "different tx.gasprice, different tx.origin", False),
        ("hook charges", "delivers 82 and keeps the difference", True),
    ]
    sworn = [
        ("unlock", "PoolManager hands control to the router", False),
        ("probe every candidate", "run each route for real, then revert", False),
        ("select", "keep the best probed delta", False),
        ("execute the winner", "same entry point, same transaction", False),
        ("assert executed == probed", "or the whole transaction reverts", True),
    ]

    # The left lane crosses a transaction boundary after step 3; that gap carries the
    # dashed rule instead of an arrow, because the boundary *is* the transition.
    BOUNDARY_AFTER = 2

    for x, steps in ((left, today), (right, sworn)):
        for i, (name, why, terminal) in enumerate(steps):
            y = y0 + i * row
            colour = SIGNAL if terminal else INK
            p.append(_box(x, y, lane, box, stroke=RULE_HARD if terminal else RULE))
            p.append(_text(x + 16, y + 20, name, size=12.5, family=MONO, fill=colour))
            p.append(_text(x + 16, y + 36, why, size=11.5, fill=FAINT))
            if i == len(steps) - 1:
                continue
            if steps is today and i == BOUNDARY_AFTER:
                rule = y + box + 14
                p.append(
                    f'  <line x1="{x}" y1="{rule}" x2="{x + lane}" y2="{rule}" '
                    f'stroke="{SIGNAL}" stroke-width="1.2" stroke-dasharray="5 4"/>'
                )
                p.append(
                    _text(
                        x + lane,
                        rule - 5,
                        "transaction boundary",
                        size=10.5,
                        family=MONO,
                        fill=SIGNAL,
                        anchor="end",
                    )
                )
            else:
                p.append(_arrow(x + lane / 2, y + box + 3, x + lane / 2, y + row - 4))

    # Everything in the right lane happens inside one transaction. Say so with a bracket.
    top = y0 - 6
    bottom = y0 + (len(sworn) - 1) * row + box + 6
    bx = right + lane + 16
    mid = (top + bottom) / 2
    p.append(
        f'  <path d="M{bx - 7} {top} H{bx} V{bottom} H{bx - 7}" fill="none" '
        f'stroke="{SIGNAL}" stroke-width="1.2"/>'
    )
    p.append(
        f'  <text x="{bx + 17}" y="{mid}" font-family="{MONO}" font-size="11" '
        f'fill="{SIGNAL}" text-anchor="middle" '
        f'transform="rotate(90 {bx + 17} {mid})">one transaction</text>'
    )

    verdict = bottom + 32
    p.append(
        _text(
            left,
            verdict,
            "The hook answered two callers. Nothing here can tell.",
            size=12,
            fill=INK,
        )
    )
    p.append(
        _text(
            right,
            verdict,
            "The hook answered one caller, once. Lying costs it the trade.",
            size=12,
            fill=INK,
        )
    )
    return _frame(
        w, verdict + 26, "\n".join(p), "How routing works today, and how it works with Sworn"
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
# `SwornRouter` reduces to a single assertion. `executedDelta == probed[chosen]`, so the
# logo is that assertion: equality, enforced inside a boundary. The brackets are the
# transaction the probe happens inside; the two bars are the two deltas that have to match.
# It is drawn rather than lettered so it survives being 16px in a browser tab, and it uses
# no colour, because on this project colour means "value a hook took" and a logo has not
# taken anything.


def _mark(size: int = 64, ink: str = INK, stroke: float = 6.6) -> str:
    """The mark: a seal with an equals struck into it.

    "Sworn" is an oath, and an oath is sealed. What this one attests is the router's single
    assertion, `executedDelta == probed[chosen]`, so the seal carries an equals sign. The
    clipped upper-right edge is what stops it reading as a generic circle: a struck seal
    deforms where the die meets it.

    Proportions are set for the smallest place it appears, a 16px browser tab, which is why
    the strokes are heavy and the two bars sit close together.
    """
    k = size / 64.0

    def pt(*vals: float) -> str:
        return " ".join(f"{v * k:.2f}" for v in vals)

    return f"""  <path d="M{pt(53, 32)} A{pt(21, 21)} 0 1 1 {pt(42, 13.6)} L{pt(53, 20)} Z"
        fill="none" stroke="{ink}" stroke-width="{stroke * k:.2f}" stroke-linejoin="round"/>
  <g stroke="{ink}" stroke-width="{stroke * k:.2f}" stroke-linecap="round">
    <path d="M{pt(21.5, 27)} H{pt(42.5)}"/>
    <path d="M{pt(21.5, 38)} H{pt(42.5)}"/>
  </g>"""


def logo() -> str:
    """The mark alone on a transparent ground, in dark ink. For light surfaces."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="Sworn">
{_mark(ink=LOGO_DARK)}
</svg>
"""


def logo_light() -> str:
    """The mark alone in light ink, for dark surfaces."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="Sworn">
{_mark(ink=LOGO_LIGHT)}
</svg>
"""


def logo_seal() -> str:
    """The mark reversed out of a dark squircle. Favicons and avatars, where the glyph
    needs a shape of its own and has to survive any background behind it."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="Sworn">
  <rect width="64" height="64" rx="16" fill="{LOGO_DARK}"/>
{_mark(ink=LOGO_LIGHT)}
</svg>
"""


def logo_wordmark() -> str:
    """Mark and wordmark locked up, on its own dark plate so it reads the same in GitHub's
    light and dark themes."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 88" width="320" height="88" role="img" aria-label="Sworn">
  <rect width="320" height="88" rx="14" fill="{LOGO_DARK}"/>
  <g transform="translate(16 12)">
{_mark(ink=LOGO_LIGHT)}
  </g>
  <text x="92" y="57" font-family="{SANS}" font-size="38" font-weight="700" letter-spacing="-1.4" fill="{LOGO_LIGHT}">SWORN</text>
</svg>
"""


def banner() -> str:
    """The cover image: the lockup and the claim on the left, the evidence on the right.

    1280x640 on purpose. That is GitHub's social-preview size and the 2:1 most submission
    forms crop to, so the image is never letterboxed or cropped through the text. Two
    columns, because at 2:1 a single left-aligned block leaves half the frame empty.
    """
    div = _load("divergence.json")
    attrib = _load("attribution.json")
    caught = _load("caught.json")

    w, h = 1280, 640
    m = 80
    col = 812  # where the evidence column starts
    p: list[str] = [f'  <rect width="{w}" height="{h}" fill="{PAPER}"/>']

    # The same faint rule grid the site uses behind its hero.
    for gx in range(160, w, 160):
        p.append(f'  <line x1="{gx}" y1="0" x2="{gx}" y2="{h}" stroke="{RULE}"/>')
    for gy in range(160, h, 160):
        p.append(f'  <line x1="0" y1="{gy}" x2="{w}" y2="{gy}" stroke="{RULE}"/>')

    # Lockup.
    p.append(f'  <g transform="translate({m} 72)">')
    p.append(f'    <rect width="80" height="80" rx="20" fill="{LOGO_LIGHT}"/>')
    p.append(_mark(size=80, ink=LOGO_DARK))
    p.append("  </g>")
    p.append(
        f'  <text x="{m + 104}" y="128" font-family="{SANS}" font-size="54" '
        f'font-weight="700" letter-spacing="-2" fill="{INK}">SWORN</text>'
    )

    # Claim.
    p.append(_text(m, 300, "A hook can quote one price", size=50, weight=700, spacing=-1.6))
    p.append(_text(m, 356, "and charge another.", size=50, weight=700, spacing=-1.6))
    p.append(
        _text(
            m,
            410,
            "Sworn is a Uniswap v4 router that makes",
            size=19,
            fill=INK2,
        )
    )
    p.append(_text(m, 438, "the quote and the trade one transaction.", size=19, fill=INK2))

    # Evidence column.
    p.append(f'  <line x1="{col - 44}" y1="72" x2="{col - 44}" y2="520" stroke="{RULE_HARD}"/>')
    into = sum(int(x["fills_into_divergent"]) for x in attrib["products"])
    stats = [
        (
            f'{int(div["totals"]["divergent_hooks"])} of {int(div["totals"]["eligible_hooks"])}',
            "measurable hooks on Base charge",
            "more than they quote",
        ),
        (
            f"{into:,}",
            "swaps routed into those hooks,",
            "through every major aggregator",
        ),
        (
            f'{int(caught["observed"]["charged_extra_bps"])} bps',
            "caught on a live Base hook, and",
            "recovered by routing around it",
        ),
    ]
    y = 168
    for figure, line1, line2 in stats:
        p.append(_text(col, y, figure, size=38, weight=700, fill=SIGNAL, spacing=-0.8))
        p.append(_text(col, y + 26, line1, size=13, fill=INK2))
        p.append(_text(col, y + 44, line2, size=13, fill=INK2))
        y += 118

    p.append(f'  <line x1="{m}" y1="520" x2="{w - m}" y2="520" stroke="{RULE_HARD}"/>')
    p.append(
        _text(
            m,
            560,
            "every figure reproducible from a hashed snapshot  ·  github.com/Aman035/sworn",
            size=14,
            family=MONO,
            fill=FAINT,
        )
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="Sworn: a Uniswap v4 router that makes the quote and the trade the same transaction">
{chr(10).join(p)}
</svg>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    drawings = {
        "logo.svg": logo,
        "logo-light.svg": logo_light,
        "logo-seal.svg": logo_seal,
        "logo-wordmark.svg": logo_wordmark,
        "banner.svg": banner,
        "routing.svg": routing,
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
