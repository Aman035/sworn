# Phase 10 — README, feedback, and the numbers behind them

> Status: DONE · Gate: `make phase-10`

## Objective

Tell the story with only numbers this repo produced.

## The mechanism

`README.md` is generated from `README.template.md`. The template contains no digits — every
figure is a placeholder:

```
{{result:divergence.json:totals.eligible_hooks|int}}
```

`scripts/render_readme.py` resolves them from `data/results/*.json`;
`scripts/verify_readme_numbers.py` fails the build on any digit in the template that did not
come from a result. Diagrams are generated the same way by `scripts/render_graphics.py`, so
a chart cannot carry a figure the data no longer supports.

A README is the one file where a stale number does the most damage and is least likely to be
noticed. A placeholder cannot go stale: it either resolves or the build fails.

## Three things the gate caught

**1. The verifier passed while the README was full of raw placeholders.** prettier pads `|`
inside markdown table cells, so `{{result:x|int}}` became `{{result:x | int}}` and stopped
matching the pattern. The staleness check could not see it, because a renderer that fails to
match produces the same unresolved text on both sides of the comparison. Fixed three ways:
the pattern now tolerates whitespace, the verifier fails on any `{{…}}` surviving into
`README.md`, and the gate refuses a placeholder inside a table row at all. Both files are in
`.prettierignore` and wrapped by hand.

**2. The rendered file can drift from its template.** Rendering in CI and forgetting to
commit would leave the published README stale while every check passed. The gate now diffs
`README.md` and `docs/assets` against a fresh render.

**3. The headline needed an honest denominator.** The gate requires
`divergence.totals.eligible_hooks` and `divergence.noise_floor` to exist. "4 of 1,404" and
"4 of 25" are very different claims and only one of them is true — the eligible set is the
hooks with enough measured fills to classify at all.

## The numbers as published

- 4 divergent hooks of 25 eligible, from a uniform sample of 10,000 Base fills
- ~48% of charged fills are measurement error, published alongside the headline rather than
  discovered by a reader
- 50.2% of fills are unattributed, published for the same reason

## Section order

Fixed by `SWORN_PLAN.md`: thesis, the property the protocol assumes, how spoofing works,
cost to exploit, measured on mainnet, the `Swap` event finding, Sworn, replay, HookBook,
detection precision, what Uniswap should change, limits, dashboard, reproduce.

The "what Uniswap should change" section is the one that pays back the measurement work:
six concrete changes, each traceable to something that cost time during this build and is
written up in [FEEDBACK.md](../../FEEDBACK.md).

## Still open

- `replay.json` is produced by Phase 6; the README's replay section describes the method and
  will carry its figures once that gate closes.
- The hooklist schema PR is drafted against the fields `HookBook` already publishes
  (`divergenceScore`, `envSensitive`, `intermittent`, `upgradeable`) and not yet opened.
