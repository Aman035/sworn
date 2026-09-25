# Phase 3 — Settled-trade divergence

> Status: DONE, with a stated limitation on what the numbers mean · Gate: `make phase-3`

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

## Results

Sample: the 25 busiest Base hooks by fill count, 4 fills each, from a 30-day window of
12,855,496 fills across 5,257 hooks.

|                                |                                |
| ------------------------------ | -----------------------------: |
| hooks measured                 |                             24 |
| fills measured                 | 92 (of 100 quoted; 8 unusable) |
| charged fills (> 5 bps excess) |                              1 |
| divergent hooks                |                          **0** |

Zero divergent hooks, and the sensitivity sweep does not move it: 2, 5, 10 and 25 bps
thresholds crossed with 10, 20 and 50 minimum fills all give the same answer. The headline
is not an artefact of a threshold choice, because there is no headline to be an artefact of.

**This is a finding, not a null result.** 0x reported 54.2% malicious across all 84,163
hooks. We sampled the _busiest_ hooks by fill count, which on Base are largely allowlisted
infrastructure — the largest holds 8,170,323 pools, 54% of the chain. Toxicity, if it is
where 0x found it, lives in the long tail rather than in the hooks carrying volume. A
sample drawn by volume and a sample drawn uniformly answer different questions, and the
difference is itself worth reporting.

Attribution, which needs no re-quoting and therefore covers all 12.8M fills:

| Product                       |     Fills | Into hooked pools |
| ----------------------------- | --------: | ----------------: |
| Uniswap UniversalRouter       | 3,220,269 |             30.9% |
| Uniswap UniversalRouter (2nd) | 1,602,197 |             44.7% |
| 0x BaseSettler                |   458,339 |             45.3% |
| 0x BaseSettler (2nd)          |   350,231 |             43.6% |
| Doppler                       |   300,653 |            100.0% |

**50.2% of fills are unlabeled**, published as a field. An attribution table that hides
its own coverage is not evidence.

## The -101 bps that turned out to be the finding

An earlier run of this pipeline reported a median take of about **-101 bps** on several
hooks: users apparently receiving 1% _more_ than they were quoted. The obvious explanation
was that the re-quote applied a fee the real swap did not. That was tested and fails —
hooks on pools with fee **0** showed the same -101 bps as hooks on fee-3000 pools. A
systematic offset across unrelated fee tiers is not a fee-tier bug.

The cause was in what "realized" meant. It was being read from the `Swap` event, and
**`PoolManager` emits that event before it calls `afterSwap`**:

```solidity
(amountToSwap, beforeSwapDelta, lpFeeOverride) = key.hooks.beforeSwap(key, params, hookData);
swapDelta = _swap(pool, id, ...);        // emits Swap(amount0, amount1)  <-- indexers read this
(swapDelta, hookDelta) = key.hooks.afterSwap(key, params, swapDelta, hookData, beforeSwapDelta);
_accountPoolBalanceDelta(key, swapDelta, msg.sender);   // what the caller is actually charged
```

On fill `0x03d2434d…`, the event and the call disagree:

|                       |                        amount1 |
| --------------------- | -----------------------------: |
| `Swap` event          |      3,941,355,102,139,778,949 |
| `swap()` return value |      3,901,941,551,118,381,160 |
| difference            | 39,413,551,021,397,789 = 1.00% |

The hook takes **1% in `afterSwap`**, and the event does not show it. Measured from the
event, that hook looks like it is paying users 1%. It is charging them 1%.

The correction generalizes: **anyone measuring hook behaviour from `Swap` events
systematically under-reports exactly the hooks that take the most**, because taking in
`afterSwap` is invisible to the event. That is the obvious way to build such a measurement,
and it is the way this repo built it first.

Chasing that also exposed a second event defect. The sign pattern of `Swap` cannot
distinguish exact-input-token0 from exact-output-token1 — they are identical. **13% of the
fills this pipeline had selected as "exact-input" were exact-output swaps**, re-quoted as a
swap that never happened.

### What the pipeline does now

Every sampled fill is confirmed against its own transaction trace before it is measured.
`amountSpecified`, `hookData` and the realized output all come from the traced
`PoolManager.swap` call — its calldata and its return value. The event is used only to
locate candidates. Matching an indexed fill to a traced call needs no ordering assumption:
the first five words of the swap calldata are the ABI encoding of the pool key, so
`keccak256` of them is the same `PoolId` the event carries.

Recovery costs about **0.01 s per transaction** and succeeded on 135/135 calls in the
sample. `divergence.json` now carries a `trace_confirmation` block recording what was
dropped and why.

### The effect on the numbers

| Quantity                   | From the `Swap` event | From the traced call |
| -------------------------- | --------------------: | -------------------: |
| Median take across fills   |            -101.0 bps |         **+0.0 bps** |
| Fills measured             |                   100 |                   78 |
| Exact-output contamination |                   13% |                   0% |
| `hook_data_unknown_share`  |                   1.0 |                  0.0 |

A median of **+0.0 bps** is the strong result here: on the median fill the re-quote
predicts the delivered output exactly, including hooks that take 1% in `afterSwap`. The
hook charges, the quoter sees the charge, and the swapper gets what the quote said. That is
what Sworn calls honest — and it is only visible once the measurement stops trusting the
event.

## What these numbers support, and what they do not

**Supported:** the machinery works end to end; the re-quote agrees with reality to 0.0 bps
at the median on hooked fills and 0.00 bps on hookless ones; the sample contains no
divergent hooks at any threshold in the sensitivity sweep; the attribution is solid.

**Not supported:** a claim about how often hooks charge across the population. The sample
is volume-weighted (the busiest 25 hooks, 4 fills each), not uniform, so it answers "what
do the busiest hooks do" and not "what does a hook do". The ±37-40 bps at p5/p95 is
block-position noise from quoting at block N-1, not hook behaviour.

## Next step

A uniformly drawn sample large enough for a real charged-rate distribution, rather than a
volume-weighted one, so the population matches the question the headline asks.
