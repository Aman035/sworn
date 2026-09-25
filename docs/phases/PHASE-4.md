# Phase 4 — `hook-probe` detection kit and precision calibration

> Status: DONE, with an uninformative precision matrix (see below) · Gate: `make phase-4`

## Objective

An open, reproducible detector for spoof-capable hooks, and an honest measurement of where
each method fails.

## The headline result

**Presence of an environment opcode is almost meaningless. Execution on the swap path is
not.** Across all 69,242 Base hooks:

| Signal                                          |  Hooks |     Share |
| ----------------------------------------------- | -----: | --------: |
| contains _any_ environment opcode               | 68,665 | **99.2%** |
| contains a simulation-**distinguishing** opcode | 26,525 | **38.3%** |
| `GAS`                                           | 68,490 |     98.9% |
| `ORIGIN`                                        | 24,543 |     35.4% |
| `GASLIMIT`                                      |  1,059 |      1.5% |
| `COINBASE`                                      |    796 |      1.1% |
| `PREVRANDAO`                                    |    464 |      0.7% |
| `GASPRICE`                                      |    199 |  **0.3%** |

`GAS` appears in almost every contract because solc emits it for every external call, so a
detector built on "contains an env opcode" flags 99.2% of the chain and says nothing.

The ordering is the surprise: **`tx.origin` is two orders of magnitude more common than
`tx.gasprice`**, the textbook spoofing signal. A detector tuned for the textbook attack
would miss almost everything.

And on the top 40 hooks by pool count, tracing narrows it much further:

| Method                                          | Flags |
| ----------------------------------------------- | ----: |
| static (contains a distinguishing opcode)       |     4 |
| differential (quote moved with the environment) |     0 |
| **trace (hook executed one while pricing)**     | **1** |

Three of the four statically-flagged hooks contain `ORIGIN`, `PREVRANDAO` or `GASLIMIT`
and **never execute one on the swap path**. One genuinely reads `ORIGIN` three times, by
the hook itself, while pricing a swap. That gap — 4 down to 1 — is what the trace method
is for, and it is why `METRICS.md` requires execution rather than presence.

## How each method works

**static** — walks the instruction stream, skipping PUSH immediates. This detail is
load-bearing: a naive `0x3a in code` scan reports `GASPRICE` in nearly every contract,
because that byte appears constantly inside pushed constants. A fixture whose constant is
deliberately made of `0x3a` and `0x41` bytes is in the gate.

**differential** — quotes the same swap under four environments (gas price 0, 1 gwei,
100 gwei, and half gas) and compares. State is identical across permutations, so anything
that moves is environment sensitivity by definition. The quoter is injected with an
`eth_call` state override rather than looked up on-chain, so probing never depends on a
deployed `V4Quoter` and always uses the version pinned here.

**trace** — `debug_traceCall`, reconstructing which contract executed each opcode from the
call stack, so a read by the `PoolManager` or a library is not attributed to the hook.

## Precision matrix: reported, and uninformative

```
  hooks scored (probed AND measured)  8
  divergent among them                0

  method          tp  fp  fn  tn   precision  recall
  static           0   0   0   8       0.00    0.00
  dynamic          0   0   0   8       0.00    0.00
  trace            0   0   0   8       0.00    0.00
  settled_trade    0   0   0   8       0.00    0.00
```

**Precision and recall here are undefined, not zero.** The scored set contains no positives
— Phase 3 found no divergent hooks in its volume-weighted sample — so there is nothing for
a detector to be right or wrong about. The pipeline prints that in as many words rather
than letting a table of `0.00`s read as "every detector failed", and the number needing
fixing is the eight-hook overlap, not the detectors.

Getting a real matrix needs Phase 3's `hookData` decoder and a uniformly drawn sample, so
that the labelled set contains hooks that actually charge.

## Gate output

```
  ok  PUSH immediates are not mistaken for opcodes
      decoy clean, real read detected
  ok  static detection is correct on compiled fixtures
      40 hooks: static flags 4, traced 40, on-path 1
  ok  probe.json validates and trace is stricter than static presence
  ok  per-method precision and recall reported against settled trades
```

The third check asserts trace flags **no more** hooks than static presence. If it ever did,
something is wrong by construction — a hook cannot execute an opcode its bytecode does not
contain.

## Decisions and deviations from the plan

- **The probe kit is Python, not a TypeScript `probe/` package.** The static analyser,
  the RPC layer and the snapshot machinery already live in `analysis/`, and the Phase 2
  gate already tests the bytecode scanner. A TypeScript rewrite would duplicate tested
  code for no capability gain. The `probe/` workspace package remains a stub.
- **The struct logger, not a custom JS tracer.** The plan implies a JS tracer; QuickNode
  returns "JS Tracer is not enabled". `debug_traceCall` with `disableMemory` and
  `disableStorage` works everywhere `debug_traceCall` does, at ~35,000 log entries and
  16 MB per trace — heavy, but fine for the hundreds of hooks a precision matrix needs.
- **Repeat probing was not implemented.** The plan notes it can detect state-independent
  randomness, and then notes that counters revert inside `eth_call` so it mostly cannot.
  The settled-trade method is the only reliable detector for dice-roll hooks, which is
  already the plan's own conclusion.

## Friction (feeds FEEDBACK.md)

- Custom JS tracers are disabled on common providers, so any tool depending on them fails
  for a large share of users. The built-in struct logger is the portable choice, but it
  returns everything and leaves attribution to the caller.
