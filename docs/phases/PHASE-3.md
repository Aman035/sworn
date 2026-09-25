# Phase 3 — Settled-trade divergence

> Status: IN PROGRESS (was BLOCKED; calibration now passes) · Gate: `make phase-3`

## Objective

The headline numbers: which hooks charge, how much, when, and who routed users into them.

## What was built

- **Fill pull** (`analysis/pipelines/b_fills.py`) — 12,855,496 `Swap` events on Base over a
  30-day window, resumable, with a guard that refuses to write a snapshot claiming a wider
  window than it covers.
- **Re-quote engine** (`contracts/script/Requote.s.sol` + `analysis/lib/requote.py`) —
  `vm.rollFork(txHash)` then a `V4Quoter` deployed _on the fork_, so the quote comes from
  the pinned periphery rather than a looked-up address. Records the block it quoted at and
  the pool's `sqrtPriceX96` there, so a surprising answer is falsifiable.
- **Calibration harness** (`scripts/calibrate_requote.py`) — the gate on everything else.

## Resolution

The blocker was a JSON parsing bug in the re-quote script, not a data problem.

`stdJson.parseRaw` returns the ABI encoding of whatever the JSON value is. Amounts were
encoded as JSON **strings** (they exceed int64 on the Python side), so that encoding is a
dynamic `bytes` and `abi.decode(…, (uint256))` read its **offset word — 32**. Every fill
was re-quoted with an input of 32, and every quote came back with the same tiny answer.

It survived a long investigation because it looked exactly like a pool with no liquidity,
and every other explanation checked out: pool key correct, fork at the right block,
pre-state price matching the event's to 2e-7, liquidity genuinely 5.5e14. The tell was
that **the output was 31 regardless of input size** — which read as "one-sided pool" but
actually meant the input never varied. Having the script echo back what it parsed
(`sent 118308819, parsed 32`) settled it in one run.

Every field now uses the typed `read*` helpers, which parse numeric strings correctly.

**After the fix, calibration passes: 19/20 within 1 bps (95%), median ratio 1.000000**,
with most fills matching to the digit.

The lesson worth keeping: a uniform bug producing _non-uniform_ results was the real
anomaly. Four fills appeared to pass, and a partial pass should have been treated as more
suspicious than a total failure.

## Why this was BLOCKED

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

| Hypothesis              | Verdict                                                                           |
| ----------------------- | --------------------------------------------------------------------------------- |
| Wrong pool key          | **No** — the reconstructed `PoolKey` hashes to the fill's `poolId` exactly        |
| Fork not rolling        | **No** — `quotedAtBlock` equals the fill's block for every sample                 |
| Wrong pre-state         | **No** — quoted-state `sqrtPriceX96` matches the fill's event price to 2e-7       |
| Same-block interference | **No** — zero PoolManager events touched the pool earlier in the block            |
| JIT liquidity in the tx | **No** — the failing transactions emit no `ModifyLiquidity`                       |
| Direction inverted      | **No** — quoting the flipped direction returns 30 instead of 31                   |
| Batch state leakage     | **No** — quoting a failing fill alone returns the same answer                     |
| Amount-dependent bug    | **No** — the quote returns **31 for every input size**, from 1,000 to 118,308,819 |

That last row is the shape of the answer: the pool is one-sided at the pre-fill state and
can only deliver 31 units in that direction. The quoter is correct _about the state it is
given_. What is unexplained is how the real transaction obtained 118,309,433 from that
same pre-transaction state, on a hookless pool, with no liquidity event in between.

## Two bugs found and fixed along the way

Both would have produced confident, wrong headline numbers.

1. **Fills were keyed by `txHash` alone.** A Base transaction carries up to 126 `Swap`
   events and **37.8% of fills share a transaction**, so quotes were matched against other
   fills' realized amounts. A fill's identity is now `(txHash, logIndex)`.
2. **The calibration could only fail in one direction.** It used `excess_take_bps`, which
   is clipped at zero by design — it answers "how much was taken from the user" — so a
   quote that came back far too _low_ scored a perfect 0.000 and passed. It reported
   "10/10 within 1 bps, calibration passed" while half the ratios were 1e-6. It now
   measures `|expected/realized − 1|`, which is what the config's
   `calibration_max_abs_excess_bps` meant by _abs_.

## Next step

Pipelines B (divergence), C (intermittency) and D (attribution), now that the engine they
depend on is verified against ground truth.
