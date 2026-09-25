# Feedback on building with Uniswap v4

Written while building [Sworn](README.md), an execution-integrity layer for v4. Everything
below is something that cost real time during this build, with the evidence in-repo.

---

## Time to first success

**Roughly four hours** from an empty directory to a passing swap through a custom router
on a locally deployed `PoolManager`, and most of that was not spent on v4 concepts.

| Step                                                  | Time | Note                                  |
| ----------------------------------------------------- | ---- | ------------------------------------- |
| Toolchain, deps, gating harness                       | ~2h  | mostly repo scaffolding, not v4       |
| Reading `Hooks.sol`, `IPoolManager`, delta accounting | ~45m | the docs were adequate here           |
| First compiling router                                | ~30m |                                       |
| First _passing_ swap                                  | ~45m | all of it spent on two problems below |

The two problems were the compiler settings and the test pool's depth. Neither is about
v4's design; both are about the gap between "the code compiles" and "the code runs".

---

## Friction, in order of cost

### 1. `optimizer_runs` is load-bearing and undocumented

At `optimizer_runs = 800` with `via_ir = true` and solc 0.8.26 — a reasonable default —
**`PoolManager` does not compile at all**:

```
Error: Yul exception: Variable memPtr_1 is 1 too deep in the stack
```

The error names a Yul internal and says nothing about optimizer settings. v4-core's own
`foundry.toml` uses `optimizer_runs = 44444444`, and matching it fixes the build
immediately. That number is effectively a hard requirement for anyone compiling v4-core,
and it appears in no integration guide we found.

**Suggestion:** state the required compiler settings in the integration docs, or fail with
a message that points at them.

### 2. The `Swap` event's documentation contradicts the code

`IPoolManager.sol` documents the event as:

```solidity
/// @param amount0 The delta of the currency0 balance of the pool
```

but `PoolManager.sol:241` emits `delta.amount0()` — the **swapper's** delta, which is the
opposite sign. Anyone building an indexer from the natspec gets every fill backwards, and
the error is silent: amounts look plausible, just inverted.

This repo's analysis depends on that sign, and it was only settled by reading the emission
site.

**Suggestion:** correct the natspec. It is a one-line fix that prevents a whole class of
downstream error.

### 3. The `Swap` event cannot be used to measure what a swapper received

This is the same event as #2 and a separate, worse problem. `PoolManager.swap` emits `Swap`
**between** `beforeSwap` and `afterSwap`:

```solidity
(amountToSwap, beforeSwapDelta, lpFeeOverride) = key.hooks.beforeSwap(key, params, hookData);
swapDelta = _swap(pool, id, ...);     // emits Swap(amount0, amount1)
(swapDelta, hookDelta) = key.hooks.afterSwap(key, params, swapDelta, hookData, beforeSwapDelta);
_accountPoolBalanceDelta(key, swapDelta, msg.sender);
```

The ordering is deliberate and the code says so. The consequence is not documented: the
event's amounts **exclude anything the hook takes in `afterSwap`**, so for a delta-returning
hook they are neither the swapper's input nor the swapper's output.

Measured on Base, one hook taking 1% in `afterSwap`:

| `amount1`             |                                  value |
| --------------------- | -------------------------------------: |
| `Swap` event          |              3,941,355,102,139,778,949 |
| `swap()` return value |              3,901,941,551,118,381,160 |
| difference            | 39,413,551,021,397,789 — exactly 1.00% |

Read from the event, that hook appears to hand users an extra 1%. It charges them 1%. Any
dashboard, analytics product or hook-scoring system built on `Swap` events
**systematically under-reports exactly the hooks that take the most**, because taking in
`afterSwap` is invisible to the event — and building on the event is the obvious approach.
This repo built it that way first and spent a day chasing the resulting -101 bps offset
through fee tiers and `hookData` before reading the emission order.

A third problem compounds it: the event's sign pattern cannot distinguish exact-input on
token0 from exact-output on token1. They are identical. 13% of the fills we had classified
as exact-input from the event were exact-output.

Both are only recoverable from `debug_traceTransaction` — the calldata for
`amountSpecified` and `hookData`, the return value for the true delta. That works and costs
about 0.01 s per transaction, but it requires an archive node with the debug namespace,
which puts an accurate measurement out of reach of anyone working from logs alone.

**Suggestion:** two options, either of which closes it.

1. Document on `IPoolManager.Swap` that the amounts are pre-`afterSwap` and are not the
   swapper's realized amounts, and say where to get those instead.
2. Better: emit the caller's final delta. A `SwapSettled(id, sender, amount0, amount1)`
   after `_accountPoolBalanceDelta`, or an `afterSwap` hook-delta field on the existing
   event, would make hook take measurable from logs. Without it, "how much did this hook
   charge" is not an answerable question at the log layer, which seems at odds with hooks
   being the headline feature.

### 4. `v4-periphery` has no release tags, and its `main` does not build against `v4-core`'s

`v4-periphery` publishes no tags at all, so every integrator pins an arbitrary `main`
commit. Worse, that `main` is built against a **later** `v4-core` than the `v4.0.0` tag:
`SwapParams` and `ModifyLiquidityParams` moved from `IPoolManager` into
`types/PoolOperation.sol`, so `V4Quoter` will not compile against the released core.

Keeping both versions is not an option — the compiler then has two distinct `IPoolManager`
types, and a `PoolKey` built from one cannot be passed to a quoter built from the other.
The only way through is to abandon the release tag and pin the commit periphery pins.

`permit2` has a related problem: its only git tag is the _deployed address string_, which
is not a version.

**Suggestion:** tag `v4-periphery` releases, and state which `v4-core` each is built
against. This is the single biggest source of avoidable setup cost.

### 5. Provider behaviour makes "just read the logs" a research project

Nothing here is Uniswap's fault, but it is the dominant cost of building anything
data-driven on v4, and a first-party indexing story would remove it. Across one census:

| Failure                           | Provider          | Correct response        |
| --------------------------------- | ----------------- | ----------------------- |
| `413` on response size            | QuickNode         | shrink the block window |
| 10-block `eth_getLogs` cap        | Alchemy free tier | shrink, or upgrade      |
| `429`                             | both              | wait, do **not** shrink |
| `503` mid-pull                    | QuickNode         | retry, do not shrink    |
| `failed to get logs for block #N` | QuickNode         | retry; may be permanent |

Conflating any two of these either corrupts the data or wastes hours. A 10.6%-complete BNB
census died on a single 503 before this was handled.

**Suggestion:** a published, paginated log/fill feed for `PoolManager` events would let
integrators skip this entirely.

### 6. Address-encoded permissions are excellent; the tooling around them is thin

Deriving permissions from the hook address is a genuinely good design — it makes
capability checks free and unforgeable. Confirmed against all **4,961** hooklist entries
with zero disagreements.

What is missing is the inverse: given an address, a one-call way to get its permissions in
a non-Solidity context. Every integrator re-implements the bit decoding.

**Suggestion:** publish the decoding as a tiny library in the SDK, and include the decoded
permissions in `hooklist.json`.

---

## The missing capability

**There is no way for a hook to prove it is honest, and no way for a router to find out
cheaply.**

`hooklist` records provenance — name, deployer, verified source, upgradeability — and
nothing about behaviour. That asymmetry has a predictable outcome: routers that get burned
respond by dropping hooked pools wholesale, which punishes exactly the builders the
ecosystem needs. On Base, **98.5% of pools carry a hook**, so "avoid hooks" is not a
strategy anyone can actually adopt.

Measured while building this:

- **69,242** distinct hooks on Base; **15.1%** are upgradeable
- **99.2%** contain an environment opcode — a presence-based detector flags nearly the
  whole chain
- but only **38.3%** contain one that could distinguish a simulation, and tracing shows
  most of those never execute it while pricing
- `ORIGIN` appears in **35.4%** of hooks; `GASPRICE`, the textbook spoofing signal, in
  **0.3%**

A detector tuned for the textbook attack would miss almost everything.

---

## The one improvement with the greatest impact

**Add behavioural fields to the hooklist schema, and expose them in the Trading API.**

Three fields would do it: `divergenceScore`, `envSensitive`, `intermittent` — each with
the block it was measured at and a hash of the dataset behind it, so anyone can re-derive
rather than trust. This repo publishes exactly that shape on-chain in `HookBook`
(`0x8A4470f7DDa8525b484527b21B19c3bc876A04c3` on Base Sepolia), and a generator that fills
the hooklist fields from it is the Phase 10 pull request.

The critical detail, learned the hard way: **absence of a score must not read as a good
score.** An unmeasured hook has to be distinguishable from a measured-clean one, or the
cheapest route to a perfect rating is to deploy and not trade. `HookBook` returns
`INSUFFICIENT_DATA` rather than 0, and the SDK rejects unscored hooks when a ceiling is
requested.

And the honest limit of the whole idea: **reputation lags, and a hook can toggle between
transactions.** Enso observed a pool toxic for 423 of 718 hours, switched 26 times. No
registry refreshed on human timescales can track that. Scores make honesty legible; only
in-transaction verification makes spoofing impossible. Both are needed, and neither
substitutes for the other.

---

## What worked well

- **Address-encoded permissions.** Unforgeable, free to check, and correct in every one of
  the 4,961 entries we tested.
- **Flash accounting.** Probing several routes inside one `unlock` and letting the losing
  probes revert is natural in v4 and would be painful in v3.
- **Transient storage for the lock.** EIP-1153's revert semantics are what make Sworn's
  guarantee hold: a hook cannot count how many times it has been probed, because the
  probe's revert rolls back its own bookkeeping. This is tested in
  `test_gasSniff_probeStateIsRolledBack`.
- **`vm.rollFork(txHash)`.** Re-quoting a settled fill against the state immediately before
  it is a one-line cheatcode, and it is the foundation of every number in this repo.
