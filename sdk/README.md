# sworn-sdk

Build `SwornRouter` calldata, and read `HookBook` scores.

```bash
pnpm add sworn-sdk viem
```

## What this gives you

`SwornRouter` probes every candidate route **inside the transaction that executes**,
picks the best, and reverts if the executed amount differs from the probed one. A hook
cannot show one price and deliver another, because there is no separate quote to lie to.

Nothing in this SDK is load-bearing for that guarantee. What it adds is a candidate set
that is coherent, and a way to read the advisory scores.

## Swap

```ts
import { buildSwornCall } from 'sworn-sdk';

const call = buildSwornCall({
  router: SWORN_ROUTER,
  tokenIn: WETH,
  tokenOut: USDC,
  amount: 10n ** 16n,
  minOut: 0n,
  recipient: me,
  candidates, // every pool for the pair, hooked and hookless
});

await wallet.sendTransaction(call);
```

**Pass more candidates, not fewer.** Adding a route can only improve the outcome — the
router probes them all and picks the best — and that property is asserted by
`testFuzz_moreCandidatesNeverHurts`. Passing a single toxic pool gets you the guarantee
that its price is real, and nothing more.

## Refusing hooks by score

```ts
import { HookBookReader, prepareSwornSwap } from 'sworn-sdk';

const hookBook = new HookBookReader(publicClient, HOOK_BOOK, { maxAgeSeconds: 3600n });

const call = await prepareSwornSwap({
  ...args,
  maxHookScore: 20,
  hookBook,
});
```

This is a **gas optimisation and a policy knob, not a safety mechanism**. The router's
guarantee holds whatever the score says; filtering only avoids paying to probe hooks
already measured as bad.

Two deliberate behaviours:

- **An unscored hook is refused**, not waved through. Absence of a score is not evidence
  of honesty — if it were, the cheapest route to a clean rating would be to deploy and
  never trade.
- **A stale score is treated as no score.** Falling back to the last known good value is
  precisely what an attacker who could stall the attestor would want.

## Reading a score

```ts
import { explain } from 'sworn-sdk';

const result = await hookBook.get(hook);
console.log(explain(result));
// "score 67/100 (DIVERGENT, ENV_SENSITIVE)"
// or "never measured — absence of a score is not evidence of honesty"
```

## Candidate validation

`buildSwornCall` rejects a candidate set where a route starts in the wrong token, ends in
the wrong token, or has a disconnected intermediate leg. The router compares probed
outputs as raw numbers and cannot tell that two routes ended in different tokens, so a
malformed set is the most dangerous input there is — it is caught here rather than
on-chain.

## Reference

| Export                           | Purpose                                       |
| -------------------------------- | --------------------------------------------- |
| `buildSwornCall`                 | calldata for `swornSwap`                      |
| `prepareSwornSwap`               | same, with an optional score ceiling          |
| `swornSwap`                      | build and send                                |
| `filterByScore`                  | drop candidates failing a ceiling             |
| `validateCandidates`             | check a set before sending                    |
| `HookBookReader`                 | cached score reads, `isAcceptable`, freshness |
| `explain` / `explainFlags`       | render a score in words                       |
| `swornRouterAbi` / `hookBookAbi` | for direct use                                |

See `examples/agent-swap.ts` for a complete agent flow.
