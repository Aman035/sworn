# Phase 8. `sworn-sdk`

> Status: DONE · Gate: `make phase-8`

## Objective

Make Sworn adoptable in one call.

## What it does

```ts
const call = buildSwornCall({ router, tokenIn, tokenOut, amount, minOut, recipient, candidates });
await wallet.sendTransaction(call);
```

Plus `prepareSwornSwap` with an optional `HookBook` score ceiling, `HookBookReader` with
caching and freshness, and `explain()` to render a score in words.

## The part worth defending: candidate validation

`SwornRouter` compares probed outputs as raw numbers. It has no way to know that two
routes ended in _different tokens_: it would simply pick the larger number. That makes a
malformed candidate set the most dangerous input the router can receive, and it is the
integrator who constructs it.

So the SDK rejects, before anything reaches the chain, a set where a route starts in the
wrong token, ends in the wrong token, or has a disconnected intermediate leg. Each is a
test.

## Two deliberate behaviours

**The default hook margin is 5 bps, not 0.** A hooked route carries more ways to fail: a
revert, a griefing hook, more gas, so equal pricing should not win it the route.
Integrators who disagree pass `hookMarginBps: 0`.

**A stale score is treated as no score.** Falling back to "last known good" is precisely
what an attacker who could stall the attestor would want. `HookBookReader` takes
`maxAgeSeconds` and refuses anything older.

Neither is load-bearing for the guarantee: the router's assertion holds whatever the SDK
does. Score filtering is a gas optimisation and a policy knob, and the README says so
rather than implying the SDK is what keeps a user safe.

## Gate output

```
  ok  strict typecheck passes
  ok  calldata, validation, scores and policy        (39 tests)
  ok  dist and type declarations emitted
      SwornParams has 11 fields, all present in the SDK ABI
  ok  SDK ABI matches the compiled SwornRouter
  ok  agent quickstart typechecks against a real viem client
```

Two checks in there exist because of specific risks:

- **The ABI is hand-written**, so the SDK has no build-time dependency on a Foundry
  artifact. That is only safe if the two are compared, so the gate reads the compiled
  `SwornRouter.json` and asserts every `SwornParams` field appears in `sdk/src/abi.ts`.
- **The quickstart must typecheck against a real viem client.** It initially did not, and
  that exposed a genuine bug: `ReadClient` was declared too narrowly for viem's generic
  `readContract`, so any consumer passing a real `PublicClient` would have failed to
  compile. The example is now part of the gate.

## Decisions and deviations from the plan

- **`ReadClient.readContract` is typed loosely**, with the reason in a comment. viem
  constrains `functionName` to a union derived from the ABI, which a narrow structural
  interface widens to `string` and breaks. The looseness is contained: this package owns
  the ABI, the function names and the decoding.
- **Quote adapters are not built.** The plan lists a Uniswap Trading API adapter. Deriving
  candidates from the index is the more important path. Phase 6 showed that of 17
  hookless pools for a pair, only 5 had any liquidity, so a candidate set built from an
  external quote or from fee tiers alone hands the router routes that cannot trade. That
  belongs with the index in Phase 9.
- **No UniswapX filler executor.** Deferred to Phase 11 with the other integrations.
