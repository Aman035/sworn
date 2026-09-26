# Scoring

How a hook's `divergenceScore` is computed, why each input is weighted the way it is, and
the section that matters most to an honest builder: **how to get your hook to 0**.

The formula lives in `analysis/lib/scoring.py`, its constants in `analysis/config.yaml`,
its definition in [`METRICS.md`](METRICS.md), and its on-chain home in
`contracts/src/HookBook.sol`. A test reproduces the worked example below exactly, so if
this document and the code ever disagree, the test suite fails rather than a developer
being misled.

---

## The formula

```
score = round(100 × Σ wᵢ · fᵢ × decay)

fᵢ      = min(1, inputᵢ / full_atᵢ)        numeric inputs
fᵢ      = 1 or 0                            boolean inputs
decay   = 0.5 ^ (days_since_last_evidence / half_life_days)
```

| Input            | Weight | Saturates at       | What it measures                            |
| ---------------- | -----: | ------------------ | ------------------------------------------- |
| `charged_rate`   |   0.30 | 0.50               | how often a user is hurt                    |
| `median_excess`  |   0.25 | 1,000 bps          | how badly, when it happens                  |
| `intermittency`  |   0.15 | 10 crossings / 30d | defeats one-shot checks and slow allowlists |
| `env_sensitive`  |   0.15 | boolean            | proves intent: pool state cannot explain it |
| `owner_switches` |   0.05 | 5                  | the operator can turn it on at will         |
| `upgradeable`    |   0.05 | boolean            | today's bytecode is not tomorrow's          |
| `revert_gated`   |   0.05 | 0.25 asymmetry     | griefing is a cost even without extraction  |

Weights sum to 1.0, so the score is a genuine 0–100 scale rather than an arbitrary index.

### Why behaviour outweighs properties, 0.55 to 0.10

`charged_rate` and `median_excess` together carry more than half the score because they
are the only inputs that describe what actually happened to a user. `upgradeable` and
`owner_switches` are _capabilities_: a hook can hold them and never abuse them, so they
are scored lightly. A proxy hook that has never charged anyone scores 5, not 50.

### Why `env_sensitive` is weighted like harm

At 0.15 it sits above the other capability inputs, and deliberately so. Pool state can
explain a large fee; it cannot explain a fee that changes with `tx.gasprice`. Environment
sensitivity is the closest thing to evidence of _intent_ that a measurement can produce,
which is why `METRICS.md` requires the opcode to execute on the swap path rather than
merely appear in the bytecode. Presence alone would flag 99.2% of hooks on Base and mean
nothing.

### Why evidence decays

Half-life is 14 days. A hook that stopped charging a month ago should not carry the same
score as one charging today, but it should not snap to zero either, because the operator
who switched it off can switch it back on. Exponential decay is the honest middle, and it
gives a reformed hook a visible path back.

---

## Worked example

A hook with charged rate 0.42, median charged excess 1,800 bps, 6 hourly crossings in 30
days, environment-sensitive, 2 owner-setter transactions, not upgradeable, revert
asymmetry 0.05, last charged fill 3 days ago:

```
charged_rate    min(1, 0.42/0.50)  = 0.840 × 0.30 = 0.2520
median_excess   min(1, 1800/1000)  = 1.000 × 0.25 = 0.2500
intermittency   min(1, 6/10)       = 0.600 × 0.15 = 0.0900
env_sensitive   true               = 1.000 × 0.15 = 0.1500
owner_switches  min(1, 2/5)        = 0.400 × 0.05 = 0.0200
upgradeable     false              = 0.000 × 0.05 = 0.0000
revert_gated    min(1, 0.05/0.25)  = 0.200 × 0.05 = 0.0100
                                     Σ            = 0.7720
decay           0.5^(3/14)                        = 0.8620
score           round(100 × 0.7720 × 0.8620)      = 67
```

Reproduced by `analysis/tests/test_scoring.py::test_worked_example_from_metrics_doc`.

---

## No score is not a good score

A hook with fewer than `min_fills_for_score` fills (20) gets **`score = null`** and the
`INSUFFICIENT_DATA` flag. Never 0.

This is the single most important property in the design, and it cuts both ways:

- A hook cannot earn a clean rating by not trading. Otherwise the cheapest way to a
  perfect score would be to deploy, wait, and turn toxic later.
- An honest builder's 0 actually means something, because it can only be reached by
  being measured.

`HookBook` preserves the distinction on-chain: `hasScore(hook)` is false for an unscored
hook and `flags(hook)` returns `INSUFFICIENT_DATA`. The SDK's `explain()` renders it as
_"never measured. Absence of a score is not evidence of honesty"_, and
`isAcceptable(hook, maxScore)` **rejects** unscored hooks rather than passing them.

The attestor skips them too: publishing 0 for an unmeasured hook would destroy the
distinction the contract works to keep.

---

## How to get your hook to 0

Written for hook developers, in the order that matters.

**1. Do not read the transaction environment on the swap path.**
`tx.gasprice`, `tx.origin`, `block.coinbase`, `block.basefee`, `block.prevrandao` and
`gaslimit` have no legitimate role in pricing a swap. If you need them for access control,
read them outside `beforeSwap`/`afterSwap`, or accept that a trace will show them on the
path and the flag will be set. This input is worth 0.15 on its own and is the strongest
signal of intent in the model.

**2. Price from pool state, not from who is asking.**
A fee that varies with `msg.sender` is indistinguishable from one that varies with whether
it thinks it is being simulated. If you must treat callers differently, publish the rule.

**3. Keep the fee stable, or make its inputs observable.**
Dynamic fees are not penalised. `DYNAMIC_FEE` is a flag, not a weight. What is penalised
is a fee that a quote could not have predicted. If your fee depends on volatility or
inventory, it is derivable from state and a quote at the same state will match it.

**4. Do not toggle.**
Intermittency is worth 0.15 and is the pattern allowlists cannot catch. A hook that is
honest 60% of the time is not 60% honest; it is a hook nobody can route through safely.

**5. Consider giving up upgradeability, or document it.**
Worth only 0.05, so it is not disqualifying, but an immutable hook is one whose measured
history describes its future. 15.1% of hooks on Base are upgradeable.

**6. Trade.** With fewer than 20 fills you are `INSUFFICIENT_DATA`, which routers
gating on score will treat as unroutable. Getting to 0 requires being measured.

**7. Verify your source.** Not weighted. `VERIFIED` is a flag, but it is what lets a
reader check that the bytecode does what you say. Almost no hooks on Base are verified.

### Disputing a score

Every score carries the sha256 of the snapshot it was computed from, stored on-chain in
`HookBook.proof(hook).snapshotHash`. Re-run the pipelines against that snapshot and you
get the same number, or you have found a bug. Either way the conversation is about data
rather than about trust. Open an issue with the snapshot hash and the hook address.

---

## Limits

- **`divergent` is a measurement, not an accusation.** A buggy hook and a malicious one
  look identical in fill data.
- **The score says nothing about LP harm.** A hook can be scrupulously honest to swappers
  and extract from liquidity providers.
- **It is advisory.** `SwornRouter`'s guarantee does not consult it. A wrong or stale
  score cannot cause a bad fill, at most it costs gas by skipping a probe.
- **Scores lag.** Fresh evidence takes an attestor cycle to reach the chain, which is
  exactly why per-transaction verification exists and per-hook reputation is not enough.
