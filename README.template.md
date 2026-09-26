<!--
  Generated file: edit README.template.md, then `make readme`.
  Every number resolves from data/results/*.json; typing a digit here fails CI.
  Tables marked {{table:...}} are generated from the same files.
-->

[![Sworn — execution integrity for Uniswap v4](docs/assets/landing.png)](https://aman035.github.io/sworn/)

**On 14 September 2026, 0x published
[*"Uniswap v4 hooks were a mistake"*](https://0x.org/post/uniswap-v4-hooks-were-a-mistake).**
They analysed {{cite:0x.org:84,163}} hooks across six chains and reported **{{cite:0x.org:54.2%}} malicious, {{cite:0x.org:19.4%}} safe**, with some hooks delivering *"as much as {{cite:0x.org:50%}} less at execution than the amount quoted"*.

**The next day, Hayden Adams replied `"skill issue"`** — and, more substantively, that
malicious contracts have existed in every version of Uniswap, and that
**the Uniswap API only integrates hooks that have been reviewed**, so users going through
official interfaces are shielded.
([Crypto Briefing](https://cryptobriefing.com/0x-criticizes-uniswap-v4-hooks-malicious/),
[Coin Edition](https://coinedition.com/uniswap-founder-defends-v4-upgrade-over-fud-and-misunderstanding/))

**This repo takes 0x's finding as given** and asks the three narrower questions their post
leaves open, with tooling anyone can run.

## 1. Does review protect you?

No. [`0x1f91c998…`](https://basescan.org/address/0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc) is **on Uniswap's official hooklist with verified source**, and takes a median {{result:divergence.json:hooks[address=0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc].median_charged_excess_bps|bps}} above its stated fee on {{result:divergence.json:hooks[address=0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc].net_charged_rate|pct0}} of its fills, worst observed take {{result:divergence.json:hooks[address=0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc].max_charged_excess_bps|bpspct}}.

Review is a check on identity at a point in time. This is behaviour, now — and
{{result:census.json:chains[chain=base].upgradeable|int}} hooks on Base sit behind a proxy, so the code that was reviewed is not
necessarily the code that runs.

## 2. Can anyone measure this from logs?

No, and that is the finding worth the most. `PoolManager` emits `Swap` **before**
`afterSwap`, so the event excludes whatever the hook takes there. Every indexer,
dashboard and hook-scoring tool built on `Swap` events under-reports exactly the hooks
that take the most. This repo did it that way first, and spent a day chasing the
resulting offset before reading the emission order.

Measured properly — from the traced call rather than the event, with the measurement's
own error subtracted — **{{result:divergence.json:totals.divergent_hooks|int}} of {{result:divergence.json:totals.eligible_hooks|int}}** hooks with enough fills to classify are
charging more than they quote.

## 3. Can it be closed at execution time?

Yes, and not by detecting anything: static, differential and trace analysis all scored
**zero recall** against ground truth here. `SwornRouter` moves the quote **inside the
transaction that settles it** — probe every candidate for real, revert, take the best,
and assert that what executed equals what was probed. A hook that lies makes those two
disagree, and the trade does not happen.

# The problem

## What a hook is allowed to do

A v4 hook runs inside `PoolManager.swap`. In `beforeSwap` it can reduce the amount being
swapped or override the fee; in `afterSwap` it can take a further delta out of the result.
Both hook calls receive the same arguments whether the caller is a simulator or a
transaction — but the *environment* differs, and the hook can read it:

- `tx.gasprice` is `0` under `eth_call` and non-zero in a transaction
- `tx.origin` is commonly the zero address in a simulator
- `block.coinbase` and `block.basefee` are frequently zeroed too

A hook that branches on any of them is honest to every quoting engine that exists and
dishonest to the person paying. **The cost to build one is a modifier.** No privileged
position, no capital, no race to win — the hook is already inside every swap that touches
its pool.

![How a quote-spoofing hook behaves differently under simulation](docs/assets/attack.svg)

## Uniswap's own surfaces point the wrong way

This is not a hypothetical the docs warn about. Three things found while building this,
all written up with reproductions in [FEEDBACK.md](FEEDBACK.md):

1. The [`Swap` event natspec](https://github.com/Uniswap/v4-core/blob/main/src/interfaces/IPoolManager.sol)
   documents `amount0` as *"the delta of the currency0 balance of the pool"*. The code
   emits the **swapper's** delta — the opposite sign. Every indexer built from the docs is
   inverted.
2. The **"Access msg.sender"** guide teaches hooks to read the caller, without noting that
   routers therefore cannot trust a quote.
3. The Trading API defaults to **hooks-inclusive** routing, and allowlisting is the only
   defence anyone ships — a defence against *identity*, not against *behaviour*.

## Measured on mainnet

Every v4 pool on four chains, indexed from `Initialize` logs. No subgraph, no third-party
index.

![Pools indexed per chain, and the hooked share](docs/assets/census.svg)

Then a **uniform random sample of {{result:divergence.json:trace_confirmation.sampled|int}} Base fills**, each re-quoted against the
state immediately before it and compared with what the swapper actually received:

- **{{result:divergence.json:totals.fills|int}}** fills measured, across **{{result:divergence.json:totals.hooks|int}}** hooks
- **{{result:divergence.json:totals.eligible_hooks|int}}** of those hooks had enough fills to classify at all
- **{{result:divergence.json:totals.divergent_hooks|int}} charge more than they quote**

### The hooks, named

{{table:divergent_hooks}}

`✓ hooklist` means the hook is on Uniswap's official allowlist with verified source.
**The worst offender is one of them**: [`0x1f91c998…`](https://basescan.org/address/0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc)
is listed, source-verified, and takes a median **{{result:divergence.json:hooks[address=0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc].median_charged_excess_bps|bps}} above its stated
fee** on {{result:divergence.json:hooks[address=0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc].net_charged_rate|pct0}} of its fills, with a worst observed take of
{{result:divergence.json:hooks[address=0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc].max_charged_excess_bps|bpspct}}. An allowlist keyed on address cannot express that.

Every figure resolves from [`divergence.json`](data/results/divergence.json), which carries
the sha256 of the snapshot it was computed from.

### Half the signal is noise, and that is published too

A hook cannot deliver **more** than it quoted, so any fill measured as over-delivering is a
known false positive — and because the error is symmetric, its count estimates the false
positives among the charged fills:

- **{{result:divergence.json:noise_floor.charged_fills|int}}** charged fills
- **{{result:divergence.json:noise_floor.overdelivered_fills|int}}** over-delivered — impossible from hook behaviour, so pure error
- **{{result:divergence.json:noise_floor.estimated_false_positive_share|pct}}** estimated false-positive share
- **{{result:divergence.json:noise_floor.hooks_failing_the_floor|int}}** eligible hooks failed the floor and were dropped

Counting positives alone reports a much larger number. Subtracting each hook's own negative
tail leaves {{result:divergence.json:totals.divergent_hooks|int}}, and the published figure is the smaller one. The full
before-and-after is in [PHASE-3.md](docs/phases/PHASE-3.md).

## Why nobody has noticed

The `Swap` event omits the `afterSwap` take, as above. The two numbers, for a hook taking
exactly one percent:

| `amount1`             |                                          value |
| --------------------- | ---------------------------------------------: |
| `Swap` event          |                    `3,941,355,102,139,778,949` |
| `swap()` return value |                    `3,901,941,551,118,381,160` |
| difference            | `39,413,551,021,397,789` — exactly one percent |

A second, independent defect: the event's sign pattern cannot distinguish exact-input on
token0 from exact-output on token1. They are identical, and **{{result:divergence.json:trace_confirmation.dropped.exact-output|int}}** of the sampled fills
turned out to be exact-output swaps the event had disguised.

So every fill here is confirmed against its own transaction trace — `amountSpecified`,
`hookData` and the realized output all come from the traced `PoolManager.swap` call. Of
{{result:divergence.json:trace_confirmation.sampled|int}} sampled fills, {{result:divergence.json:trace_confirmation.confirmed|int}} survived confirmation. Both defects are filed
upstream in [FEEDBACK.md](FEEDBACK.md).

## Detection does not catch it either

Four ways to flag a spoofing hook, each scored against what hooks actually did to settled
trades:

{{table:detection}}

![Precision and recall of each hook detection method](docs/assets/precision.svg)

**No static, differential or trace detector caught either divergent hook** among those both
probed and measured. Only re-quoting settled trades did — and that is retrospective by
construction: it works after someone has already been paid less than they were quoted.

A score tells you what a hook did last week. It cannot tell you what it is doing to your
transaction right now.

## Who is routing into this

Attribution covers every fill and publishes its own blind spot.

{{table:attribution}}

**{{result:attribution.json:unlabeled_share|pct}} of fills are unattributed**, reported rather than dropped, because a table
that hides its coverage is not evidence. The products above are not doing anything wrong —
they are doing the normal thing, which is to trust a quote.

---

# The solution

`SwornRouter` moves the quote **inside the transaction that settles it**. Every candidate
route is executed for real and then reverted, the best is taken, and the router asserts
that what executed equals what it probed.

![How SwornRouter probes candidates inside the transaction](docs/assets/mechanism.svg)

Three details carry the guarantee:

- **Probe and execution share one entry point.**
  [`runRoute(hops, amountSpecified, probing)`](contracts/src/SwornRouter.sol#L201) is the
  same external self-call either way, so a hook observes identical gas and call context.
  `probing` is read only *after* every externally observable call.
- **A probe reverts, so state rolls back** — including EIP-1153 transient storage
  ([`UNLOCKED_SLOT`](contracts/src/SwornRouter.sol#L77)). A hook cannot leave itself a note
  saying "that was a probe".
- **The assertion is the product.**
  [`revert Divergence(chosen, probed, executed)`](contracts/src/SwornRouter.sol#L178) fires
  when execution disagrees with the probe. The user does not get a worse fill; the user
  gets no fill.

Because the probe *is* the real environment, there is nothing left for a hook to
distinguish. It cannot answer the probe honestly and the execution dishonestly, because
they are the same call, in the same transaction, at the same gas price.

## Verified against live mainnet hooks

[`RealSwap.fork.t.sol`](contracts/test/fork/RealSwap.fork.t.sol) forks Base and routes
ETH → USDC through hooks that are live right now:

```
delivered USDC: 133138269
reported out  : 133138269
```

The swap completes, the tokens received **equal** the amount the router reported, and the
divergence check held against real hook bytecode at real liquidity. Two further tests cover
a dynamic-fee hook and a sole hookless candidate.

## What the guarantee costs

![What the guarantee is worth](docs/assets/landing-value.png)

Probing costs a **fixed** amount of gas and saves a **proportion** of the trade, so it pays
above a trade size and not below it:

- break-even trade size: **${{result:replay.json:totals.breakeven_notional_usd|f2}}**
- median protection where a better route existed: **{{result:replay.json:totals.median_protection_bps|f2}} bps**
- median cost to protect one trade: **${{result:replay.json:totals.probe_gas_usd_median|f4}}**
- {{result:replay.json:totals.fills_protected|int}} of {{result:replay.json:totals.fills_with_alternatives|int}} fills with an alternative had a better one

A router should not probe a two-dollar swap, and `maxProbes` and `hookMarginBps` exist so an
integrator can set that line. Gross dollars across the priceable subset were
${{result:replay.json:totals.protected_usd_gross|f2}} protected against ${{result:replay.json:totals.probe_gas_usd|f2}} of gas — a real sum and a
misleading one, since a uniform sample of Base fills is mostly dust and
{{result:replay.json:totals.gas_cost_top10_share|pct0}} of that gas came from ten transactions. Full working in
[PHASE-6.md](docs/phases/PHASE-6.md).

Measured probe overhead, verbatim from `forge test --match-contract SwornGasTest`:

```
  baseline (NaiveRouter, 1 pool, no probe)   111,553
  swornSwap, 1 candidate                     204,270   overhead vs naive  +92,717
  swornSwap, 2 candidates                    275,159   overhead vs naive +163,606
  swornSwap, 3 candidates                    341,845   overhead vs naive +230,292
```

## HookBook, and what it refuses to say

[`HookBook`](contracts/src/HookBook.sol) is an on-chain registry of hook scores written by a
scheduled attestor. Its load-bearing property is how it handles **absence**:

- an unscored hook returns `hasScore() == false` and `FLAG_INSUFFICIENT_DATA`
  ([`flags`](contracts/src/HookBook.sol#L124)) — **never a clean zero**
- a hook with too few measured fills gets `score = null`; a good rating has to be earned
- updates are monotonic in `asOfBlock` ([`StaleUpdate`](contracts/src/HookBook.sol#L83)),
  which is replay and staleness protection in one
- scores are EIP-712 signed ([`setScoreWithSig`](contracts/src/HookBook.sol#L198)), so
  anyone can relay an attestation and pay for it

| Network      | `HookBook`                                                                                                                                  | Status                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Base Sepolia | [`0x8A4470f7DDa8525b484527b21B19c3bc876A04c3`](https://sepolia.basescan.org/address/0x8A4470f7DDa8525b484527b21B19c3bc876A04c3) | Live, attestor authorised, scores written |
| Base mainnet | —                                                                                                                                             | Not deployed; `1,643,224` gas to do so    |

The attestor wrote {{result:divergence.json:totals.eligible_hooks|int}} scores; a second scheduled run correctly wrote nothing,
because the registry already held that block. Scoring is specified in
[SCORING.md](docs/SCORING.md), with a worked example the test suite reproduces exactly.

---

# Demo

```bash
./scripts/demo.sh
```

Three acts, ordered by how hard each is to fake. No manual steps, and every figure is
produced by the EVM during the run — the gate greps the source to prove no `console.log`
string contains a number.

| Act | What runs                                                     | What it shows                                                                    |
| --- | ------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `1` | `DemoTest` on a local chain                                    | A hook quotes well at `tx.gasprice = 0`, delivers 17.99% less at a real gas price, and Sworn recovers 21.95% by routing around it |
| `2` | `RealSwap.fork.t.sol` on anvil forked from Base                | The same router completes ETH → USDC through **live mainnet hooks** |
| `3` | `app/` static export                                           | The dashboard, rendered from the same result files as this README |

Storyboard, including what the demo deliberately does **not** show, in
[DEMO.md](docs/DEMO.md).

[![The Sworn hook explorer](docs/assets/dashboard-hooks.png)](https://aman035.github.io/sworn/hooks/)

Three pages behind the landing, all rendered from the same `data/results/*.json` this
README is:
[Hooks](https://aman035.github.io/sworn/hooks/) ·
[Detection](https://aman035.github.io/sworn/detection/) ·
[Attribution](https://aman035.github.io/sworn/attribution/)

---

# Project outline

```
contracts/src         SwornRouter (probe-and-assert), HookBook (on-chain scores)
contracts/test        unit, fuzz, invariant, toxic fixtures, mainnet fork
analysis/lib          RPC, log fetching, compaction, re-quoting, trace recovery, scoring
analysis/pipelines    census -> fills -> divergence -> intermittency -> attribution -> replay -> scores
app                   Next.js dashboard, static export
attestor              scheduled job that writes HookBook
sdk                   buildSwornCall: calldata from a quote, viem action
docs                  METRICS.md defines every term *before* it is measured
scripts/gates         one script per phase; `make phase-N` is the only way a phase closes
```

## Where to verify the integration

| What                                                     | Where                                                                      |
| -------------------------------------------------------- | -------------------------------------------------------------------------- |
| Entry point, validates candidates and opens the v4 lock   | [`swornSwap` · SwornRouter.sol#L121](contracts/src/SwornRouter.sol#L121)    |
| `IUnlockCallback`; all routing happens inside the lock    | [`unlockCallback` · #L140](contracts/src/SwornRouter.sol#L140)              |
| **The guarantee**: execution must equal the probe         | [`revert Divergence` · #L178](contracts/src/SwornRouter.sol#L178)           |
| One entry point for probe and execution                   | [`runRoute` · #L201](contracts/src/SwornRouter.sol#L201)                    |
| A probe must revert; reaching the end means the EVM lied  | [`ProbeMustRevert` · #L228](contracts/src/SwornRouter.sol#L228)             |
| Probe isolation via a derived transient slot (EIP-1153)   | [`UNLOCKED_SLOT` · #L77](contracts/src/SwornRouter.sol#L77)                 |
| EIP-150 `63/64` rule, so a griefing hook cannot starve it | [`_assertStipend` · #L251](contracts/src/SwornRouter.sol#L251)              |
| Recovering what a swap actually did, from its trace       | [`analysis/lib/swapcalls.py`](analysis/lib/swapcalls.py)                    |
| Every modelled attacker capability, as a fixture          | [`ToxicHooks.sol`](contracts/test/fixtures/ToxicHooks.sol)                  |

## Reproduce everything

```bash
cp .env.sample .env          # archive RPC per chain; keys never leave the file
make install
make test                    # forge + pytest + vitest
make phase-3                 # the gate that produced divergence.json
make phase-6                 # fork tests against live Base hooks, then replay
make readme                  # re-render this file and its diagrams from data/results
```

Every result file carries `meta.snapshots[]` with a sha256 of its input snapshot and the
commit of the script that produced it. A number that cannot be traced to a snapshot is a
number this repo will not print — enforced by
[`verify_readme_numbers.py`](scripts/verify_readme_numbers.py), which fails the build on any
digit in this file that did not come from a result.

---

# What Uniswap should change

1. **Emit the caller's final delta.** A `SwapSettled` event after
   `_accountPoolBalanceDelta`, or an `afterSwap` delta field on the existing event. Without
   it, "how much did this hook charge" is not answerable from logs at all.
2. **Fix the `Swap` natspec.** It documents the pool's delta; the code emits the swapper's.
3. **Carry behaviour in the hooklist**, not just identity: `divergenceScore`,
   `envSensitive`, `intermittent`, `upgradeable`. Proposal with data in
   [HOOKLIST_PROPOSAL.md](docs/HOOKLIST_PROPOSAL.md).
4. **Point the "Access msg.sender" guide at in-transaction verification.**
5. **Expose per-route hook scores in the Trading API.**
6. **Document the required compiler settings.** `optimizer_runs = 800` cannot compile
   `PoolManager`, and the error names a Yul internal.

# Threat model and limits

- **The divergence sample is small.** {{result:divergence.json:totals.eligible_hooks|int}} hooks clear `min_fills`, out of
  {{result:census.json:chains[chain=base].hooks_total|int}} on Base. It establishes that the measurement works and that
  divergent hooks exist; it is not a population rate.
- **The precision table rests on two positives.** Directionally clear, statistically thin.
- **Accurate measurement needs an archive node with `debug_traceTransaction`.** That is a
  property of v4, not of this repo, and it is the first item in [FEEDBACK.md](FEEDBACK.md).
- **Candidate routes are quoted with empty `hookData`**, because no router called them.
- **`HookBook` scores are advisory.** The guarantee is the probe.
- **A hook that is honest to everyone is still honest under Sworn.** This defends against
  quote/execution divergence, not against a hook that charges a large fee openly.

Full model in [THREAT_MODEL.md](docs/THREAT_MODEL.md) ·
[METRICS.md](docs/METRICS.md) · [GAS.md](docs/GAS.md) · [PHASES.md](PHASES.md)
