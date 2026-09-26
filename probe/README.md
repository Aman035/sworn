# `probe/` — superseded by `analysis/`

The plan called for a TypeScript hook-probe kit: static bytecode analysis, differential
`eth_call`, and `debug_traceCall`. All three exist and run, in Python:

| Planned here | Actually built |
| ------------ | -------------- |
| `probe/static` — env opcodes, proxy pattern, owner-gated setters | [`analysis/lib/evm.py`](../analysis/lib/evm.py) |
| `probe/dynamic` — permuted `eth_call` environments | [`analysis/lib/probe.py`](../analysis/lib/probe.py) |
| `probe/trace` — `debug_traceCall` with call-stack attribution | [`analysis/lib/probe.py`](../analysis/lib/probe.py) |
| `probe/report` — merged per-hook output | [`analysis/pipelines/f_probe.py`](../analysis/pipelines/f_probe.py) → `data/results/probe.json` |

**Why the change.** The probe's output is only meaningful next to the settled-trade
measurement it is scored against, and that comparison — `data/results/precision.json` — is
pandas. Splitting the two across languages would have meant a serialisation boundary in the
middle of a single question.

The result is worth reading: against hooks that were both probed and measured, **static,
differential and trace detection all scored 0.00 precision and 0.00 recall.** Only
re-quoting settled trades caught anything. That table is the argument for verifying
in-transaction instead of detecting in advance, and it is why this package staying a stub
costs the project nothing.

This package is kept as a workspace member so the layout still matches `SWORN_PLAN.md`.
Nothing imports it.
