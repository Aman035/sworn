# Phase 3 — Settled-trade divergence

> Status: **BLOCKED** · Gate: `make phase-3`

## Objective

The headline numbers: which hooks charge, how much, when, and who routed users into them.

## What was built

- **Fill pull** (`analysis/pipelines/b_fills.py`) — 12,855,496 `Swap` events on Base over a
  30-day window, resumable, with a guard that refuses to write a snapshot claiming a wider
  window than it covers.
- **Re-quote engine** (`contracts/script/Requote.s.sol` + `analysis/lib/requote.py`) —
  `vm.rollFork(txHash)` then a `V4Quoter` deployed *on the fork*, so the quote comes from
  the pinned periphery rather than a looked-up address. Records the block it quoted at and
  the pool's `sqrtPriceX96` there, so a surprising answer is falsifiable.
- **Calibration harness** (`scripts/calibrate_requote.py`) — the gate on everything else.

## Why this is BLOCKED

The calibration fails: **4 of 10 hookless fills re-quote exactly, 6 do not.**

```
expected=2474228455934366424307   realized=2474228455934366424307   |dev|=    0.0 bps
expected=138870958                realized=138870958                |dev|=    0.0 bps
expected=173919671                realized=173919671                |dev|=    0.0 bps
expected=46904288                 realized=46904288                 |dev|=    0.0 bps
expected=592                      realized=265524857698566558       |dev|=10000.0 bps
expected=31                       realized=118309433                |dev|=10000.0 bps
...
within 1.0 bps : 4/10 (40%)   required >= 95%
```

`docs/METRICS.md` requires hookless pools to show ~zero excess take, so this is a stop
condition, not a tuning opportunity.

## What has been ruled out

Each of these was tested, not assumed:

| Hypothesis | Verdict |
| ---------- | ------- |
| Wrong pool key | **No** — the reconstructed `PoolKey` hashes to the fill's `poolId` exactly |
| Fork not rolling | **No** — `quotedAtBlock` equals the fill's block for every sample |
| Wrong pre-state | **No** — quoted-state `sqrtPriceX96` matches the fill's event price to 2e-7 |
| Same-block interference | **No** — zero PoolManager events touched the pool earlier in the block |
| JIT liquidity in the tx | **No** — the failing transactions emit no `ModifyLiquidity` |
| Direction inverted | **No** — quoting the flipped direction returns 30 instead of 31 |
| Batch state leakage | **No** — quoting a failing fill alone returns the same answer |
| Amount-dependent bug | **No** — the quote returns **31 for every input size**, from 1,000 to 118,308,819 |

That last row is the shape of the answer: the pool is one-sided at the pre-fill state and
can only deliver 31 units in that direction. The quoter is correct *about the state it is
given*. What is unexplained is how the real transaction obtained 118,309,433 from that
same pre-transaction state, on a hookless pool, with no liquidity event in between.

## Two bugs found and fixed along the way

Both would have produced confident, wrong headline numbers.

1. **Fills were keyed by `txHash` alone.** A Base transaction carries up to 126 `Swap`
   events and **37.8% of fills share a transaction**, so quotes were matched against other
   fills' realized amounts. A fill's identity is now `(txHash, logIndex)`.
2. **The calibration could only fail in one direction.** It used `excess_take_bps`, which
   is clipped at zero by design — it answers "how much was taken from the user" — so a
   quote that came back far too *low* scored a perfect 0.000 and passed. It reported
   "10/10 within 1 bps, calibration passed" while half the ratios were 1e-6. It now
   measures `|expected/realized − 1|`, which is what the config's
   `calibration_max_abs_excess_bps` meant by *abs*.

## Next step

Characterise the failing population rather than exclude it by hand: for a larger sample,
partition by whether the pre-state can produce the realized amount at all, and find what
distinguishes the two groups. The restriction that survives becomes a documented
population definition in `METRICS.md`, not a filter chosen to make a number look good.

Until the calibration clears 95%, no divergence, intermittency or attribution number is
computed, and `data/results/` gains no file from this phase.
