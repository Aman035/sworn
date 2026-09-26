# Phase 5. `SwornRouter` and toxic fixtures

> Status: DONE · Gate: `make phase-5`

## Objective

The mechanism, correct at the v4 level, with adversarial fixtures modelling every observed
toxic pattern.

## The claim, measured

A gas-price-sniffing hook quotes free to a simulator and charges 18% to a real
transaction: the median take 0x reported for the Base hook `0x800cef…a5c7`. Measured by
`test_reportSpoofGapAndRecovery`:

```
quoted at gasprice=0       996,999,005,991,991
delivered if forced toxic  817,539,331,628,894
delivered through Sworn    996,999,005,991,991
spoof gap                  1,799 bps  (17.99%)
recovered                  2,195 bps  (21.95%)
```

Sworn returns the user to the honest price exactly.

## What it costs

From `SwornGasTest`, against `NaiveRouter`: a slippage-only router that does what a
competent router does today:

| Route                         |     Gas | Overhead |
| ----------------------------- | ------: | -------: |
| NaiveRouter, 1 pool, no probe | 111,553 |        . |
| `swornSwap`, 1 candidate      | 204,270 |  +92,717 |
| `swornSwap`, 2 candidates     | 275,159 | +163,606 |
| `swornSwap`, 3 candidates     | 341,845 | +230,292 |

Each additional candidate costs about 68,000 gas and the cost is linear, which is the
design: one more candidate is one more probe, not a re-run of the route. On Base at
0.006 gwei a three-candidate swap's overhead is a fraction of a cent.

## Attacker coverage

Every capability in `THREAT_MODEL.md` has a fixture and a passing test.

| #   | Capability                  | Fixture                    | Outcome                                    |
| --- | --------------------------- | -------------------------- | ------------------------------------------ |
| 1   | Gas-price sniffing          | `GaspriceSniffHook`        | routed around                              |
| 2   | Origin sniffing             | `OriginSniffHook`          | routed around                              |
| 3   | Coinbase / basefee sniffing | `CoinbaseBasefeeSniffHook` | routed around                              |
| 4   | Dice roll, block-sourced    | `DiceRollBlockHook`        | probe sees the true roll                   |
| 5   | Dice roll, counter-sourced  | `DiceRollCounterHook`      | probe's revert rolls the counter back      |
| 6   | Owner switch                | `OwnerSwitchHook`          | routed around while toxic, usable once off |
| 7   | Router whitelisting         | `RouterWhitelistHook`      | avoided when toxic, used when honest       |
| 8   | Gas-left sniffing           | `GasSniffHook`             | identical `gasleft()` in both phases       |
| 9   | Callback probing            | `CallbackSniffHook`        | router answers identically                 |
| 10  | Revert griefing             | `RevertGriefHook`          | candidate skipped, swap succeeds           |
| 11  | Gas burning                 | `GasBurnHook`              | bounded by the stipend, swap succeeds      |
| 12  | **Anything unmodelled**     | `CheatingDivergentHook`    | `Divergence` reverts; user loses nothing   |

Two of these are worth singling out.

**The hook observes exactly the same gas.** `RecordingGasSniffHook` measured 1,932,728 in
both the probe and the execution. Identical. That is EIP-150's 63/64 rule not biting,
demonstrated rather than argued.

**The safety net is tested by defeating it.** Every other fixture loses because the EVM
gives a hook no way to distinguish a probe from an execution. `CheatingDivergentHook`
cheats: it keeps its invocation count _host-side_ via cheatcodes, where the probe's revert
cannot reach, quotes free and then charges. No deployable hook can do this: that is the
point. The test proves that when the threat model's reasoning is wrong, the transaction
reverts and the user's balance is unchanged. **Denial, not theft.**

## Gate output

```
  ok  solc 0.8.26, via-IR, cancun
  ok  unit, fuzz and invariant tests pass
  ok  all twelve attacker capabilities from THREAT_MODEL.md are covered
  ok  Divergence assertion is exercised by a hook that defeats the probe
      SwornRouter lines 141/150 = 94.00%
  ok  line coverage >= 90%
  ok  probe overhead measured against a slippage-only router
```

62 tests: unit, four fuzz properties at 512 runs each, exact-output, multi-hop, native ETH.

## Decisions and deviations from the plan

- **`optimizer_runs = 44444444`, matching v4-core.** Not tuning: at 800 runs, solc 0.8.26
  with via-IR cannot compile `PoolManager` at all ("Variable memPtr_1 is 1 too deep in the
  stack"). Anything that compiles v4-core has to use v4-core's setting.
- **v4-core moved from `v4.0.0` to `59d3ecf`.** v4-periphery's `main` is built against a
  later core where `SwapParams` moved into `PoolOperation.sol`, and `V4Quoter` will not
  compile against the tag. Two versions would give the compiler two distinct
  `IPoolManager` types. See `ARCHITECTURE.md`.
- **The gas table is a dedicated benchmark, not `forge test --gas-report`.** Gas
  instrumentation interferes with `vm.txGasPrice`, which disarms the spoofing fixtures: the report would keep passing while measuring nothing. Caught because two tests failed
  only under `--gas-report`.
- **Probe and execution share one `runRoute` entry point.** The plan asks for
  byte-identical calldata; that is not literally achievable since the two calls must
  differ somehow. They share a selector and a prologue, and the only differing parameter
  is read _after_ every externally observable call, so gas at hook entry is identical, which is the property that actually matters, and is tested.

## Friction (feeds FEEDBACK.md)

- `forge coverage` compiles without via-IR, so a script that builds fine in the normal
  profile can be stack-too-deep under coverage. The failure names a line inside an
  unrelated file and does not mention the profile difference.
- `vm.getCode("File.sol:Name")` does not resolve for these fixtures under Foundry 1.5.1;
  only the explicit `out/…json` path works, and the miss reads like a test-logic failure.
- Forge runs test functions in parallel, and `vm.setEnv` mutates process environment,
  which is not thread-safe. A recorder built on it failed a different subset of tests on
  every run.
