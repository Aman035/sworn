# Phase 6. Fork tests and Sworn replay

> Status: DONE · Gate: `make phase-6`

## Objective

Show the router works against real chains, and measure what it is worth.

## A swap that completes through a live mainnet hook

The other fork tests assert the router never retains value, which a revert also satisfies.
[`RealSwap.fork.t.sol`](../../contracts/test/fork/RealSwap.fork.t.sol) asserts the harder
thing, against hooks live on Base:

```
delivered USDC: 133138269
reported out  : 133138269
```

0.05 ETH → 133.14 USDC through a real hooked pool, with the tokens received **equal** to the
amount the router reported, the divergence check holding, and nothing retained. Two more
tests cover a dynamic-fee hook (which picks its fee inside `beforeSwap`, so probe and
execution each ask it fresh) and a sole hookless candidate (where probe and execution must
agree exactly, or the router is wrong).

### The pool that broke the first attempt

A large family of Base tokens (vanity addresses of the form `0xb2…01`) return a
one-byte `0xef` from `eth_getCode`, which is the EOF prefix rather than runnable bytecode.
On chain they work normally: supply, decimals, and thousands of `Transfer` logs. Inside a
Foundry fork they do not, because forge fetches code with `eth_getCode`, receives `0xef`,
and executing that is an invalid opcode. A swap into one settles on mainnet and reverts on
a fork with `OpcodeNotFound` four frames down, inside `transfer`.

That is a tooling limitation, not a broken token, and it constrains which measured fills
can be replayed in a fork test at all.

The fork tests therefore route ETH to USDC, where both sides execute under a fork.

## What the router is worth

`e_replay.py` takes the same trace-confirmed fills Phase 3 measured, quotes every other pool
that could have filled each trade against the same pre-fill state, and takes the difference
when a candidate beat what the user actually got. Net of probe gas at the price that fill
actually paid.

|                                          |            |
| ---------------------------------------- | ---------: |
| fills considered                         |      8,968 |
| fills where an alternative venue existed |      3,478 |
| fills a candidate would have improved    |        105 |
| median protection on those               |  65.16 bps |
| median cost to probe one trade           |    $0.0045 |
| **break-even notional**                  | **$22.77** |

**The honest headline is the break-even, not the total.** Probing costs a fixed amount of
gas and saves a proportion of the trade, so it pays above a trade size and not below it. On
Base that size is about **$23**. A router should not probe a two-dollar swap, and Sworn's
`maxProbes` and `hookMarginBps` exist precisely so an integrator can set that line.

The gross dollar figures are published and are deliberately not the headline: $1.22
protected against $20.28 of gas, a net of **−$19.05** across the priceable subset. That is a
real sum and a misleading one: a uniform sample of Base v4 fills is mostly dust, and **92%
of the gas total comes from ten transactions** paying an unusually high priority fee. Both
the median and that concentration are in `replay.json` so the disagreement is visible rather
than discovered.

## Three things excluded on purpose

**Implausible candidates.** The largest "protection" in the raw run was 10,090,820 bps: a
thousandfold, on a fill of 49 microtokens, from a mispriced dust pool. Counting that would
have been the single easiest way to fabricate an ROI figure. Anything above 5,000 bps is cut
and the count published (`implausible_fills: 2`).

**Unpriceable outputs.** Protection denominated in a token nothing can value is not
protection anyone can spend. Those fills
still count in the bps median; they never reach the dollars. The priceable share is
published as `price_confidence: 7.3%`.

**Guessed prices.** ETH/USD comes from the deepest hookless ETH/USDC pool **at the fill's
own block**, chosen by measuring all four standard tiers rather than hard-coding one. An
earlier version quoted the WETH/USDC pool instead of the native one and got 880 USDC/ETH
against a true 2,660: a rate wrong by a factor of three is worse than no rate at all.

## Limits

- Candidates are quoted with empty `hookData`, because no router called them and there is
  nothing to recover.
- At most four candidate venues per pair, ranked hookless-first then by fee tier. A deeper
  search would find more protection and cost more gas; the trade-off is the integrator's.
- The 3.0% hit rate is over fills that _had_ an alternative at all. 5,490 of 8,968 fills
  were on pairs with a single pool, where there is nothing for any router to choose between.
