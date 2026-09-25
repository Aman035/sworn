# Phase 6 — Fork tests on the hooks 0x named

> Status: IN PROGRESS · Gate: `make phase-6`

## Objective

Prove the mechanism against real deployed hooks, not only against fixtures we wrote.

## What the census got right

Both hooks named in the 0x report of 14 September 2026 were located in our census, and the
`PoolKey` we reconstructed for each hashes to a pool that is live on-chain. That is a
strong check: a wrong key hashes to a pool id that was never initialized, and `slot0`
would read zero.

| | Base hook `0x800cef…a5c7` | BNB hook `0x141984…c880` |
| --- | --- | --- |
| Pair | ETH / `0xb2000…108c` | USDT / WBNB |
| 0x reported | "ETH/NVDAc", median 18% when charged | "USDT/WBNB", fee range 0–12.8% |
| Fee mode | dynamic (`0x800000`) | dynamic (`0x800000`) |
| Permission bits | `0x25c7`, includes `AFTER_SWAP_RETURNS_DELTA` | `0x0880`, **no returns-delta** |
| `sqrtPriceX96` at pin | 2,726,724,300,712,797,452,135,401 | 3,007,820,621,519,910,873,998,791,271 |
| Liquidity at pin | 4,184,499,386,950,196 | **0 (dormant)** |
| Fills in 30d window | 1,088 | — |

**The two hooks take value by different mechanisms.** The Base hook holds
`AFTER_SWAP_RETURNS_DELTA` and can skim an arbitrary share of the output. The BNB hook
holds no returns-delta permission at all — it can only override the dynamic fee, which is
exactly the "0–12.8% fee range" shape 0x described. A census that treats returns-delta as
the marker of a dangerous hook would miss the second one entirely.

## What the probe saw

On a fork of Base at block 51,700,000, `swornSwap` was given two real candidates: the
hook's pool and the most liquid hookless pool for the same pair. Both probed successfully
inside the transaction:

```
candidate 0 (hook 0x800cef…a5c7)   amountIn 1e16   amountOut 11,774,493
candidate 1 (hookless, fee 10%)    amountIn 1e16   amountOut  9,983,990
```

**The hooked pool probed 17.9% more output than the hookless one.** At probe time — inside
the real transaction, at a real gas price — this hook prices *better*, which is how a hook
wins routing in the first place. Sworn selected it on its probed merits, which is the
correct behaviour: the guarantee is that what executes equals what was probed, not that
hooked pools are avoided.

## An honest limitation

The execution of that route did not complete on the fork. It failed with `OpcodeNotFound`
inside the hook's delegatecall to its implementation.

This is a toolchain artifact, not a property of Sworn or of the hook:

- our contracts compile with `solc 0.8.26`, whose newest EVM target is `cancun`;
- Foundry uses the compiled `evm_version` for the forked EVM as well;
- Base has since moved past cancun, so live bytecode using newer opcodes cannot execute.

Setting `evm_version = "prague"` in a profile has no effect — `forge config` still reports
`cancun`, because solc 0.8.26 cannot target it. Raising solc would break the pin that
v4-core requires (see `ARCHITECTURE.md`), so this is a genuine constraint rather than a
setting we neglected.

What this does **not** undermine: the probe results above are real, and the router's
behaviour on revert is correct — the user's balance was unchanged and the router retained
nothing, asserted in both fork tests.

## Also learned

**A candidate set built from fee tiers is not a candidate set.** Of the 17 hookless pools
our census found for the Base pair, only **5 had any liquidity** at the pinned block, and
the cheapest by fee (75 = 0.0075%) had none. Choosing candidates by fee alone hands the
router routes that cannot trade. The test now selects by on-chain liquidity, and Phase 8's
SDK should derive candidates the same way.

**The BNB hook is dormant.** Its pool is initialized but holds zero liquidity at the
pinned block. A hook that charged $18,592 and then went quiet is exactly the case the
scoring model's decay term exists for — and exactly why a per-hook reputation cannot
replace a per-transaction check.

## Remaining for this phase

- Pipeline E (Sworn replay): protected value over Phase 3's charged fills.
- Gas benchmarks per chain in USD (`docs/GAS.md`).
- A fork block where a named hook is both liquid and charging, from Phase 3's output.
