# Phase 2 — Hook census and base indexer

> Status: DONE · Gate: `make phase-2`

## Objective

Enumerate every v4 hook and pool on the target chains. This is the denominator for
everything: a divergence rate means nothing without a trustworthy count of what exists.

## What was measured

| Chain | Pools | Hooked | Distinct hooks | Blocks |
| ----- | ----: | -----: | -------------: | ------ |
| Base | 15,309,659 | 15,076,019 (98.5%) | 69,242 | 25,350,988 – 51,778,292 |
| BNB | 256,187 | 45,060 (17.6%) | 6,363 | 45,970,610 – 123,972,139 |
| Ethereum | 143,218 | 34,459 (24.1%) | 8,582 | 21,688,329 – 26,055,251 |
| Arbitrum | 19,143 | 4,752 (24.8%) | 840 | 297,842,872 – 508,800,002 |

Unichain is excluded: the available endpoint is on Alchemy's free tier, which caps
`eth_getLogs` at a 10-block range and blocks `debug_traceCall` entirely.

## Findings worth keeping

**Base is not like the others.** 98.5% of its pools carry a hook, against 18–25%
elsewhere. Hooked pools are not a niche on Base; they are the platform.

**The distribution is extremely skewed.** 15.1M hooked pools come from 69,242 hooks — a
mean of 218 pools per hook — but the single largest hook holds 8,170,323 pools, 54% of the
chain, and it is allowlisted.

**Presence of an environment opcode is almost meaningless.** Across all 69,242 Base hooks:

| | |
| --- | ---: |
| contains *any* environment opcode | 68,665 (99.2%) |
| contains a **simulation-distinguishing** opcode | 26,525 (38.3%) |
| `GAS` | 98.9% |
| `ORIGIN` | 35.4% |
| `GASPRICE` | 0.3% |

`GAS` appears in almost every contract because solc emits it for every external call. A
detector built on "does the bytecode contain an env opcode" would flag 99.2% of Base and
say nothing. This is why `METRICS.md` requires the opcode to *execute on the swap path*.

The ordering is also a surprise: `tx.origin` is two orders of magnitude more common than
`tx.gasprice`, the textbook spoofing signal. Whether those reads are on the swap path or
in ordinary access control is Phase 4's question.

**15.1% of Base hooks are upgradeable** (EIP-1967/1822 slots or an Etherscan-detected
proxy), so for one hook in six the measured bytecode is not a guarantee about future
behaviour.

**Flag decoding is independently confirmed.** Permissions derived from the address agree
with the hooklist's own declared flags for **all 4,961 entries**, zero disagreements. The
plan asked for 50 addresses.

## Gate output

```
  ok  census, decoding and reconciliation tests pass
  ok  address-derived permissions agree with Hooks.sol and all hooklist entries
  ok  census snapshots exist for: base bnb
  ok  every snapshot file hashes to its manifest
  ok  census within tolerance of a second, independent implementation
  ok  census.json validates and carries snapshot provenance
  ok  every result file references the snapshot it came from
```

Reconciliation, 40 random 2,000-block windows per chain:

| Chain | Pools (independent / snapshot) | Hooks | Delta |
| ----- | ----------------------------- | ----- | ----- |
| Base | 47,380 / 47,380 | 221 / 221 | **0.00%** |
| BNB | 246 / 246 | 24 / 24 | **0.00%** |

The tolerance is 5%; the agreement is exact. The check is deliberately a *second*
implementation: it re-requests logs from the node rather than reading the snapshot, and
decodes the hook address by byte offset instead of through `eth_abi`, so a bug in one
decoder cannot hide in the other.

## Decisions and deviations from the plan

- **No Ponder indexer.** The plan specifies Ponder for `index/`. Direct `eth_getLogs`
  with a resumable, self-compacting fetcher produced the census faster and is what the
  reconciliation check needs anyway (it must not share code with the indexer). Ponder
  remains the right tool for the *live* index in Phase 9; it was the wrong tool for a
  one-shot historical sweep.
- **Volume and TVL are deferred to Phase 3.** They need `Swap` amounts and a price source.
  `census.json` carries `volume_usd_30d: null` rather than an estimate — a fabricated
  number is worse than a missing one.
- **`metadata_hooks_covered` was added to the schema.** Etherscan is rate limited, so
  `upgradeable` and `verified` are counts *within the subset that was fetched*. Publishing
  them without their denominator would read as a claim about all 69,242 hooks.

## Friction (feeds FEEDBACK.md)

- The `Swap` event's natspec says `amount0` is "the delta of the currency0 balance of the
  pool", but `PoolManager.sol:241` emits `delta.amount0()` — the **swapper's** delta, the
  opposite sign. Anyone implementing from the documentation gets every fill backwards.
- Provider behaviour varies enough that a single fetch strategy cannot work: QuickNode
  caps on *response size* (413) while Alchemy caps on *block range*, and both emit
  transient 5xx and node-level errors during long pulls. Each needs a different response —
  shrink, wait, or retry — and conflating them either corrupts the data or wastes hours.
