<!--
  Generated file: edit README.template.md, then `make readme`.
  Every number below resolves from data/results/*.json. Typing a digit here fails CI.
-->

# Sworn

**Execution-integrity for Uniswap v4.** A hook can quote one price to a simulator and
charge another to a transaction. Sworn makes that impossible to profit from — not by
detecting it, but by refusing to settle a trade whose execution disagrees with its own
probe.

[![metrics](https://img.shields.io/badge/metrics-defined_before_measured-e8b84b?style=flat-square)](docs/METRICS.md)
[![phases](https://img.shields.io/badge/phases-gated-5a6675?style=flat-square)](PHASES.md)
[![feedback](https://img.shields.io/badge/v4_feedback-filed_upstream-e5644e?style=flat-square)](FEEDBACK.md)

---

## The problem

Every router on every chain gets its prices the same way: it asks, off-chain, what a swap
would return. A v4 hook runs inside that question and inside the answer, and it can tell
the two apart.

![How a quote-spoofing hook behaves differently under simulation](docs/assets/attack.svg)

`tx.gasprice`, `tx.origin`, `block.coinbase`, `gasleft()` — any of them distinguishes a
simulated call from a real one. A hook that reads one and prices on it is honest to every
quoting engine that exists and dishonest to the person paying. The quote is not wrong
because the simulator is bad. It is wrong because it is a different question.

You cannot fix this by simulating harder.

## The mechanism

![How SwornRouter probes candidates inside the transaction](docs/assets/mechanism.svg)

`SwornRouter` moves the quote inside the transaction that settles it. Every candidate route
is executed for real, then reverted — so the probe sees the same `tx.gasprice`, the same
`tx.origin`, the same everything a hook could key on, because it _is_ the real
environment. The best route is then executed, and the router asserts that what it got
matches what it probed.

Two details carry the guarantee:

- **Probe and execution share one entry point.** `runRoute(hops, amountSpecified, probing)`
  is the same external self-call either way, so a hook observes identical gas and call
  context. `probing` is read only after every externally observable call.
- **Reverting a probe rolls back transient storage.** EIP-1153 slots do not survive the
  revert, so a hook cannot leave itself a note saying "that was a probe".

A hook that quotes one price and executes another makes `executedDelta` differ from
`probed[chosen]`, and the transaction reverts. The user does not get a worse fill. The user
gets no fill.

## What is actually out there

![Pools indexed per chain, and the hooked share](docs/assets/census.svg)

Every v4 pool on four chains, indexed from `Initialize` logs — no subgraph, no third-party
index. On Base alone that is {{result:census.json:chains[chain=base].pools_total|int}}
pools across {{result:census.json:chains[chain=base].hooks_total|int}} distinct hooks, of
which {{result:census.json:chains[chain=base].upgradeable|int}} sit behind a proxy and can
change behaviour after anyone has reviewed them.

Hook attribution covers all fills, and publishes its own blind spot:
**{{result:attribution.json:unlabeled_share|pct}} of fills are unlabeled**. A table that
hides its coverage is not evidence.

## The finding: `Swap` events cannot measure hook take

This one is worth reading even if you never touch this repo.

`PoolManager` emits `Swap` **between** `beforeSwap` and `afterSwap`. So the event's amounts
exclude anything a hook takes in `afterSwap` — they are neither the swapper's input nor
the swapper's output. Measured on Base, for one hook taking exactly one percent there:

| `amount1`             |                                          value |
| --------------------- | ---------------------------------------------: |
| `Swap` event          |                    `3,941,355,102,139,778,949` |
| `swap()` return value |                    `3,901,941,551,118,381,160` |
| difference            | `39,413,551,021,397,789` — exactly one percent |

Read from the event, that hook appears to hand users an extra percent. It charges them.
**Any analytics built on `Swap` events under-reports exactly the hooks that take the
most**, and building on the event is the obvious approach — this repo did it first and
spent a day chasing the resulting offset through fee tiers before reading the emission
order.

A second, independent defect: the event's sign pattern cannot distinguish exact-input on
token0 from exact-output on token1. They are identical.

So every measured fill here is confirmed against its own transaction trace.
`amountSpecified`, `hookData` and the realized output all come from the traced
`PoolManager.swap` call — calldata and return value. Of
{{result:divergence.json:trace_confirmation.sampled|int}} sampled fills,
{{result:divergence.json:trace_confirmation.confirmed|int}} survived confirmation and
{{result:divergence.json:trace_confirmation.dropped.exact-output|int}} were exact-output
swaps the event had disguised. Both defects are filed upstream in [FEEDBACK.md](FEEDBACK.md).

## Why detection is not enough

![Precision and recall of each hook detection method](docs/assets/precision.svg)

Four ways to catch a spoofing hook, scored against what hooks actually did to settled
trades:

- **static** — scan bytecode for environment opcodes. Nearly every hook on Base contains
  one, so this flags nearly every hook. High recall, unusable precision.
- **differential** — quote under permuted `eth_call` environments and look for
  disagreement. Catches hooks keyed on environment, misses dice-rollers and anything keyed
  on state.
- **trace** — `debug_traceCall` with call-stack attribution, so an environment read is
  credited to the hook that made it. Better, and needs an archive node with the debug
  namespace.
- **settled trades** — re-quote real fills against real prior state. Catches everything,
  and only after someone has already been hurt.

Every row is either imprecise or retrospective. That is the argument for the router:
**a score tells you what a hook did last week; the probe tells you what it is doing to
your transaction right now.**

In the sample measured so far there are
{{result:divergence.json:totals.divergent_hooks|int}} divergent hooks at every threshold in
the sensitivity sweep. That is a real result and a small one — see
[Limitations](#limitations).

## The dashboard

![Sworn dashboard](docs/assets/dashboard.png)

Every figure renders from the same `data/results/*.json` the README does, with a provenance
rail showing the snapshot hash and block range behind each panel. Static export, no server.

```bash
cd app && npm install && npm run dev
```

## Repo

| Path                 | What                                                                |
| -------------------- | ------------------------------------------------------------------- |
| `contracts/src`      | `SwornRouter` (probe-and-assert), `HookBook` (on-chain scores)      |
| `analysis/lib`       | RPC, log fetching, compaction, re-quoting, trace recovery, scoring  |
| `analysis/pipelines` | census → fills → divergence → intermittency → attribution → scores  |
| `app`                | Next.js dashboard, static export                                    |
| `docs`               | `METRICS.md` defines every term _before_ it is measured             |
| `scripts/gates`      | one script per phase; `make phase-N` is the only way a phase closes |

## Reproduce it

```bash
cp .env.sample .env          # archive RPC per chain; keys never leave the file
make install
make test                    # forge + pytest
make phase-3                 # re-run the gate that produced divergence.json
```

Every result file carries `meta.snapshots[]` with a sha256 of the input snapshot and the
commit of the script that produced it. A number you cannot trace to a snapshot is a number
this repo will not print.

## Limitations

Stated here rather than buried, because the alternative is a headline that outruns its
evidence:

- **The divergence sample is small.** It establishes that the measurement machinery works
  end to end — the re-quote agrees with reality at the median — not how often hooks charge
  across the population.
- **Accurate measurement needs an archive node with `debug_traceTransaction`.** Everything
  above the trace layer is unavailable to anyone working from logs alone. That is a
  property of v4, not of this repo, and it is the first thing in
  [FEEDBACK.md](FEEDBACK.md).
- **Candidate routes are quoted with empty `hookData`**, because no router called them and
  there is nothing to recover.
- **`HookBook` scores are advisory.** The guarantee is the probe. A score is a hint about
  which candidates are worth probing.

## Docs

[METRICS.md](docs/METRICS.md) · [SCORING.md](docs/SCORING.md) · [GAS.md](docs/GAS.md) ·
[FEEDBACK.md](FEEDBACK.md) · [PHASES.md](PHASES.md) · [SWORN_PLAN.md](SWORN_PLAN.md)
