# Phase 1 — Story, sources, metric definitions

> Status: DONE · Gate: `make phase-1`

## Objective

Freeze what is being measured, and why, before touching data. Once a number exists it is
very hard to change a definition without the change looking like tuning; doing it in this
order makes the Phase 3 sensitivity sweep credible rather than defensive.

## What was built

- **`docs/STORY.md`** — the five claims as a table with no empty cells: claim → source →
  our artefact → phase. Each claim is owned by a file that produces it.
- **`docs/SOURCES.md`** — the external reports, with URL, date, verification status and
  the exact figures quoted. 0x and Enso were fetched and their figures transcribed
  verbatim; two Uniswap docs pages are marked `unverified` and are barred from the README
  until Phase 10 re-checks them.
- **`docs/METRICS.md`** — thirteen metrics, each with a definition, its parameters in
  `analysis/config.yaml` and its fields in `analysis/schemas/results.schema.json`,
  including the divergence-score formula and a fully worked example.
- **`docs/THREAT_MODEL.md`** — eleven attacker capabilities, what Sworn does about each,
  the gas-stipend argument, and an explicit list of what Sworn does *not* protect.
- **`docs/ARCHITECTURE.md`** — components, a mermaid data-flow diagram, the RPC capability
  matrix, and why `evm_version = cancun` is load-bearing.
- **`analysis/schemas/results.schema.json`** — all nine result files, `additionalProperties: false`
  throughout, with an `x-files` map from filename to definition.
- **`scripts/lint_docs.py`** — the gate: six checks tying the docs to the config and the
  schema in both directions.

## Gate output

```
  ok  story, sources, metrics, threat model, architecture
  ok  results.schema.json validates as a schema
  ok  metrics, parameters and result fields agree
  ok  config and schema tests pass
  ok  data/results is empty, as it must be before Phase 2
```

## Evidence

| Claim | Where it comes from | Snapshot |
| ----- | ------------------- | -------- |
| The five claims each have an owning artefact | `docs/STORY.md` table, linted for empty cells | n/a (no data yet) |
| Every metric has a parameter and a result field | `scripts/lint_docs.py` check 1 | n/a |
| External figures are quoted, not paraphrased | `docs/SOURCES.md`, fetched 2026-09-25 | n/a |
| No number has been fabricated | gate asserts `data/results/` is empty | n/a |

## Decisions and deviations from the plan

- **`mmdc` is optional.** The plan asks for a `@mermaid-js/mermaid-cli` smoke test. `mmdc`
  pulls a full Chromium download, so the linter uses it when present and otherwise runs a
  structural check (diagram type, balanced brackets, edges present). Same pattern as
  `actionlint` in Phase 0.
- **Two sources are recorded as `unverified`.** The web-search budget ran out before the
  Uniswap "Access `msg.sender`" guide and the Trading API `hooksOptions` page could be
  fetched. They are cited as motivation, marked, and blocked from the README by policy
  rather than quietly presented as checked.
- **`min_fills_for_score` yields `null`, not `0`.** A hook with too little data gets
  `INSUFFICIENT_DATA`, not a clean bill of health. This matters for claim 4: an honest
  builder needs a low score to *mean* something.
- **Dynamic-fee hooks are reported twice.** Excess over their own nominal fee, and excess
  over the nearest static tier — otherwise a dynamic-fee hook could legitimise any take by
  declaring it as its fee.

## Friction (feeds FEEDBACK.md)

- There is no machine-readable, canonical mapping from a router address to the product
  that operates it. Attribution — the question every integrator actually cares about — has
  to be hand-curated with a confidence column. A field in the hooklist schema, or an
  equivalent registry for routers, would make this reproducible rather than artisanal.
- `hooklist` records curation but no behavioural evidence, so "is this hook listed" and
  "does this hook behave" are unrelated questions with no shared vocabulary. That gap is
  what the Phase 10 schema PR proposes to close.

## Next

Phase 2 builds the census: the Ponder indexer, hook flag decoding from the address bits,
bytecode/proxy/verification detection, and the reconciliation check against an independent
`eth_getLogs` count. It is the denominator for every later number.
