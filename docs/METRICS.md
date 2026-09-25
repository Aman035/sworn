# Metrics

Frozen in Phase 1, before any data was pulled, so the numbers cannot be tuned after the
fact. Three artefacts must agree and `make phase-1` checks that they do:

| Artefact                               | Role                                          |
| -------------------------------------- | --------------------------------------------- |
| this file                              | the definition, in words, with the edge cases |
| `analysis/config.yaml`                 | every threshold, as a parameter               |
| `analysis/schemas/results.schema.json` | the field the value lands in                  |

Each metric below names its parameters and its result fields. A pipeline that hard-codes
a threshold, or writes a field not listed here, fails the gate.

**Conventions.** Amounts are in token base units. `bps` = basis points = 1/10,000.
Uniswap v4 sign convention: `amountSpecified < 0` is exact-input, `> 0` is exact-output;
deltas are signed from the caller's perspective. "Fill" means one `Swap` event in a
hooked pool. All windows are UTC.

---

## Metric definitions

### `expected_output`

**Definition.** The output of the _identical_ swap — same pool, same direction, same
`amountSpecified`, same `sqrtPriceLimitX96`, same `hookData` — evaluated against the pool
state immediately **before** the fill's transaction.

Two methods produce it:

- **exact** (primary): Foundry `vm.rollFork(txHash)`, which gives the state after every
  prior transaction in the same block, then `V4Quoter.quoteExactInputSingle` /
  `quoteExactOutputSingle`. This is the only method that is correct when another swap in
  the same block already moved the pool.
- **approx** (bulk coverage): `eth_call` against the quoter at the end of block `N-1`.
  Cheap, parallel, and wrong by the amount that earlier same-block transactions moved
  the pool. Rows produced this way carry `approx = true` and are reported separately.

`hookData` is recovered from the transaction calldata when the router's encoding is
known; when it is not, the quote is run with empty `hookData` and the row is flagged, so
a hook that only misbehaves for particular `hookData` cannot be silently mislabelled.

**Calibration.** Hookless pools must return `excess_take_bps ≈ 0`. If they do not, the
re-quote engine is wrong and no downstream number is trustworthy. This is asserted, not
assumed.

**Parameters.** `metrics.expected_output.method`, `metrics.expected_output.approx_fallback`, `metrics.expected_output.method_agreement_tolerance_bps`, `metrics.expected_output.calibration_max_abs_excess_bps`, `metrics.expected_output.calibration_min_pass_rate`, `metrics.expected_output.calibration_sample_size`

**Result fields.** `divergence.params.expected_output_method`, `divergence.hooks[].approx_share`, `divergence.hooks[].hook_data_unknown_share`, `divergence.calibration.hookless_median_excess_bps`, `divergence.calibration.method_agreement_rate`, `divergence.calibration.passed`

---

### `realized_output`

**Definition.** What the swapper actually received, taken from the `Swap` event's signed
deltas (`amount0` / `amount1`) for the fill.

Deliberately **not** measured from token transfers: a hook may move tokens to and from
the router within the same transaction, and transfer-based accounting double-counts
that. Native ETH pools (`currency0 == address(0)`) use the same delta convention.

**Parameters.** `metrics.realized_output.source`

**Result fields.** `divergence.totals.fills`, `divergence.hooks[].fills`

---

### `shortfall`

**Definition.** `(expected_output − realized_output) / expected_output`, unitless and
signed. Positive means the user received less than the pre-trade state implied. Negative
values are kept, not clipped: a hook that pays out _more_ than quoted is evidence about
the engine's accuracy and must stay visible.

For exact-output fills the comparison is made on the input side — the user's loss shows
up as paying more, not receiving less.

**Parameters.** `metrics.shortfall.clip_negative`

**Result fields.** `divergence.hooks[].median_shortfall`

---

### `take_bps`

**Definition.** `shortfall × 10,000`. The same quantity in basis points, which is the
unit every threshold and every published figure uses.

**Parameters.** `metrics.take_bps.scale`

**Result fields.** `divergence.hooks[].median_take_bps`

---

### `nominal_fee`

**Definition.** The fee the pool _says_ it charges.

- **Static-fee pools**: the LP fee encoded in the `PoolKey`.
- **Dynamic-fee pools** (`fee == 0x800000`): the fee emitted on the `Swap` event for that
  fill, because the key carries only the sentinel.

A dynamic-fee hook sets its own nominal fee, so "excess over nominal" alone would let a
hook legitimise any take by declaring it. Every dynamic-fee hook is therefore reported
twice: against its own nominal fee, and against the nearest static tier.

**Parameters.** `metrics.nominal_fee.dynamic_fee_sentinel`, `metrics.nominal_fee.dynamic_fee_source`, `metrics.nominal_fee.static_tier_reference_bps`

**Result fields.** `divergence.hooks[].nominal_fee_bps_median`, `divergence.hooks[].dynamic_fee`, `divergence.hooks[].excess_vs_static_tier_bps`

---

### `excess_take_bps`

**Definition.** `max(0, take_bps − nominal_fee_bps)`. The part of the shortfall that is
not explained by the fee the pool advertises — the "hook take".

Clipped at zero so that ordinary rounding and favourable price movement do not produce
negative "excess" that nets off real extraction in an average.

**Parameters.** `metrics.excess_take_bps.clip_at_zero`

**Result fields.** `divergence.hooks[].median_charged_excess_bps`, `divergence.hooks[].p90_charged_excess_bps`, `divergence.hooks[].max_charged_excess_bps`, `divergence.hooks[].excess_usd_total`, `divergence.totals.excess_usd_total`

---

### `charged_fill`

**Definition.** A fill with `excess_take_bps > threshold`. The threshold is 5 bps: below
that, rounding, tick crossings and same-block ordering dominate.

Because the headline count depends on this number, Phase 3 reruns the entire pipeline at
2, 5, 10 and 25 bps and publishes how the divergent-hook count moves. The published
threshold must be one of the swept values (asserted in `analysis/tests/test_config.py`).

**Parameters.** `metrics.charged_fill.threshold_bps`, `metrics.charged_fill.sensitivity_threshold_bps`

**Result fields.** `divergence.hooks[].charged_fills`, `divergence.hooks[].charged_rate`, `divergence.totals.charged_fills`, `divergence.params.charged_threshold_bps`

---

### `divergent_hook`

**Definition.** A hook with at least `min_fills` fills **and** either

- a charged rate ≥ `min_charged_rate` (it charges often), **or**
- a median charged excess ≥ `min_median_charged_excess_bps` (it charges rarely but hard).

Two arms because the two observed attack shapes are different: the env-sniffer charges
almost every simulated trade a little, the dice-roller charges a few trades enormously.
A single-arm rule misses one of them.

`min_fills` exists so that a hook with three fills cannot reach the README.

**Parameters.** `metrics.divergent_hook.min_fills`, `metrics.divergent_hook.min_charged_rate`, `metrics.divergent_hook.min_median_charged_excess_bps`, `metrics.divergent_hook.sensitivity_min_fills`

**Result fields.** `divergence.hooks[].divergent`, `divergence.totals.divergent_hooks`, `divergence.sensitivity[].divergent_hooks`, `divergence.params.min_fills`, `divergence.params.min_charged_rate`, `divergence.params.min_median_charged_excess_bps`

---

### `env_sensitive`

**Definition.** The hook's behaviour changes with the transaction environment rather than
with pool state. Established when either:

- differential probes — the same swap simulated under different `tx.gasprice`, caller
  kind and gas limit — disagree by more than `probe_disagreement_bps`; or
- a `debug_traceCall` shows an environment opcode (`GASPRICE`, `ORIGIN`, `COINBASE`,
  `BASEFEE`, `PREVRANDAO`, `GASLIMIT`, `GAS`) actually **executing on the swap path**.

Mere presence of the opcode in bytecode is _not_ sufficient: libraries and access-control
code read `tx.origin` and `gasleft()` for benign reasons. Presence is recorded as a
static signal; the flag requires execution on the path.

**Parameters.** `metrics.env_sensitive.probe_disagreement_bps`, `metrics.env_sensitive.gas_price_permutations_wei`, `metrics.env_sensitive.require_opcode_on_swap_path`, `metrics.env_sensitive.env_opcodes`

**Result fields.** `probe.hooks[].env_sensitive`, `probe.hooks[].max_disagreement_bps`, `probe.hooks[].static.env_opcodes_present`, `probe.hooks[].trace.env_opcodes_on_swap_path`

---

### `intermittent`

**Definition.** The hook's hourly charged rate crosses the charged threshold at least
`min_crossings` times within `window_days`. This is the "toggled 26 times" pattern: a
hook that is toxic for part of the day defeats any one-shot simulation _and_ any
allowlist refreshed slower than the toggle.

An hour with fewer than `min_fills_per_bucket` fills cannot count as a crossing, so a
single fill cannot flip the regime.

**Parameters.** `metrics.intermittent.window_days`, `metrics.intermittent.bucket`, `metrics.intermittent.min_crossings`, `metrics.intermittent.min_fills_per_bucket`

**Result fields.** `intermittency.hooks[].crossings`, `intermittency.hooks[].intermittent`, `intermittency.hooks[].toxic_hour_share`, `intermittency.hooks[].hourly[].charged_rate`

---

### `frontend_attribution`

**Definition.** `Swap.sender` is the contract that called `PoolManager.swap` — a router,
not the user. Mapping it to a product (a wallet, an aggregator, a filler) is how the
exposure question gets answered: _which front-end routed users into this hook?_

The map is hand-curated in `analysis/data/routers.csv` with a source URL and a confidence
per row. Anything unmapped goes to `unlabeled` and the unlabeled share is published —
an attribution table that hides its own coverage is not evidence.

**Parameters.** `metrics.frontend_attribution.router_map`, `metrics.frontend_attribution.unlabeled_bucket`, `metrics.frontend_attribution.min_confidence`

**Result fields.** `attribution.products[].product`, `attribution.products[].fills_into_divergent`, `attribution.products[].excess_usd`, `attribution.products[].confidence`, `attribution.products[].sources`, `attribution.unlabeled_share`

---

### `protected_value`

**Definition.** For a charged fill, what Sworn would have saved:

```
protected = max(0, fallback_output − realized_output) − probe_gas_cost_in_output_token
```

where `fallback_output` is the output of the best hookless pool for the same pair, quoted
at the same pre-fill state. Probe gas is charged against the saving, priced in the output
token, because a guarantee that costs more than it saves is not a saving.

USD totals are published only where the price source clears `min_price_confidence`;
fill _counts_ are published everywhere.

**Parameters.** `metrics.protected_value.probe_gas_per_candidate`, `metrics.protected_value.default_candidates`, `metrics.protected_value.min_price_confidence`

**Result fields.** `replay.totals.protected_usd`, `replay.totals.fills_protected`, `replay.totals.median_protection_bps`, `replay.totals.gas_overhead_p50`, `replay.totals.gas_overhead_p90`

---

### `divergence_score`

**Definition.** A 0–100 summary of how much a router should distrust a hook, written
on-chain by `HookBook`. Seven normalised inputs, weighted:

```
score = round(100 × Σ wᵢ · fᵢ · decay)
fᵢ = min(1, inputᵢ / full_atᵢ)        for the numeric inputs
fᵢ = 1 or 0                            for the boolean inputs
decay = 0.5 ^ (days_since_last_evidence / half_life_days)
```

| Input            | Weight | `full_at`      | Why it counts                               |
| ---------------- | ------ | -------------- | ------------------------------------------- |
| `charged_rate`   | 0.30   | 0.50           | how often a user is hurt                    |
| `median_excess`  | 0.25   | 1000 bps       | how badly, when it happens                  |
| `intermittency`  | 0.15   | 10 crossings   | defeats one-shot checks and slow allowlists |
| `env_sensitive`  | 0.15   | boolean        | proves intent: state cannot explain it      |
| `owner_switches` | 0.05   | 5              | the operator can turn it on at will         |
| `upgradeable`    | 0.05   | boolean        | today's bytecode is not tomorrow's          |
| `revert_gated`   | 0.05   | 0.25 asymmetry | griefing is a cost even without extraction  |

A hook with fewer than `min_fills_for_score` fills gets `score = null` and the
`INSUFFICIENT_DATA` flag — **not** a zero. Absence of evidence is reported as absence of
evidence, which is also what makes a low score meaningful for honest builders.

**Worked example.** A hook with charged rate 0.42, median charged excess 1,800 bps,
6 hourly crossings in 30 days, env-sensitive, 2 owner-setter transactions, not
upgradeable, revert asymmetry 0.05, last charged fill 3 days ago:

```
charged_rate    min(1, 0.42/0.50)  = 0.840 × 0.30 = 0.2520
median_excess   min(1, 1800/1000)  = 1.000 × 0.25 = 0.2500
intermittency   min(1, 6/10)       = 0.600 × 0.15 = 0.0900
env_sensitive   true               = 1.000 × 0.15 = 0.1500
owner_switches  min(1, 2/5)        = 0.400 × 0.05 = 0.0200
upgradeable     false              = 0.000 × 0.05 = 0.0000
revert_gated    min(1, 0.05/0.25)  = 0.200 × 0.05 = 0.0100
                                      Σ           = 0.7720
decay           0.5^(3/14)                        = 0.8620
score           round(100 × 0.7720 × 0.8620)      = 67
```

The flags word is a `uint32` whose bit positions are frozen in `config.yaml` under
`flags:` — `HookBook` stores it verbatim, so bits are appended, never renumbered.

**Parameters.** `metrics.divergence_score.min_fills_for_score`, `metrics.divergence_score.weights`, `metrics.divergence_score.full_at`, `metrics.divergence_score.half_life_days`

**Result fields.** `scores.hooks[].score`, `scores.hooks[].flags_bitmap`, `scores.hooks[].insufficient_data`, `scores.hooks[].inputs`, `scores.hooks[].proof`, `scores.weights`

---

## What these metrics deliberately do not measure

- **LP harm.** A hook can be perfectly honest to swappers and still be bad for liquidity
  providers. Nothing here detects that.
- **Intent.** `divergent` is a measurement, not an accusation. A buggy hook and a
  malicious one look identical in fill data; the env-sensitivity and owner-switch inputs
  are the closest available proxies for intent, and they are reported separately.
- **Off-path harm.** MEV extracted around the swap rather than inside it is out of scope.
