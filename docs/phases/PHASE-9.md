# Phase 9. Dashboard and demo

> Status: DONE · Gate: `make phase-9`

## Objective

Make the data and the guarantee visible, and keep both from rotting.

## What was built

**Dashboard** (`app/`, Next.js static export): Overview, Hook explorer, Detection,
Attribution. Every figure renders from `data/results/*.json`, with a provenance rail on each
panel showing the snapshot hash, block range and row count behind it. No server, no secrets
on the read path.

**Demo** (`scripts/demo.sh`, storyboarded in [DEMO.md](../DEMO.md)): three acts, ordered by
how hard each is to fake: a spoofing fixture on a local chain, the same router against
real Base hooks on anvil forked from mainnet, then the dashboard.

## The two decisions worth recording

**The demo is a test.** `contracts/test/unit/Demo.t.sol` is narrated with `console.log` and
asserted with `assertGt`. If the story stops being true, CI fails. The gate additionally
greps the source to prove that **no `console.log` string literal contains a figure**. Every
number reaching the screen came out of the EVM during that run. A demo whose numbers are
typed in is a slideshow.

Its current output:

```
ACT 2  What a quote sees. tx.gasprice = 0, as in every eth_call.
  pool B quotes: 996999005991991
ACT 3  What a real transaction gets. Same pool, same size.
  pool B delivers: 817539331628894
  taken without being quoted (bps): 1799
ACT 4  Sworn probes both pools inside the transaction that settles.
  naive router, trusting the quote: 817539331628894
  sworn router, probing in-tx    : 996999005991991
  recovered (bps): 2195
```

**The smoke tests read HTML, not a browser.** The plan specified Playwright. The export is
fully static, so every figure is baked into the file at build time and a browser would only
confirm that Chrome can display a string already there. `app/test/export.test.ts` asserts
the same properties by reading the built HTML, in milliseconds, without flaking.

What it guards is the failure this dashboard is actually prone to: a result file changing
shape, and every figure silently rendering `undefined`, `NaN` or an empty string while the
layout still looks perfect. It also asserts each page carries provenance, and that the hook
explorer never presents an unmeasured hook as clean.

That trade gives up layout and interaction coverage. Responsive behaviour is handled in
`globals.css` and checked by hand at 375–1440px; the data table scrolls sideways inside an
`overflow-x: auto` container rather than squeezing an address across two lines.

## What the gate caught

The export tests failed on first run, for a real reason: the detection page renders its
precision table only when there is at least one positive, and `precision.json` still held
the run from when zero hooks were divergent. Re-running `f_precision` against the corrected
divergence result populated it, and produced the sharpest number in the repo:

| method        | precision | recall |
| ------------- | --------: | -----: |
| static        |      0.00 |   0.00 |
| dynamic       |      0.00 |   0.00 |
| trace         |      0.00 |   0.00 |
| settled_trade |      1.00 |   1.00 |

**No static, differential or trace detector caught either divergent hook** in the 22 hooks
that were both probed and measured. Only re-quoting settled trades did, and that is
retrospective by construction. Small sample, but it is the whole argument for the router in
one table.

## Limits

- The demo's act 2 routes through real hooks, but none of those pools was measured as
  divergent. The swap completing is the claim; it is not a catch.
- Scores are published to Base Sepolia. The mainnet `HookBook` deploys from the same script
  and needs only funding.
- `docs/assets/dashboard.png` is a screen capture, so it is the one asset the renderer does
  not rebuild.
