# Threat model

First draft, Phase 1. Phase 5 adds a row per fixture and the test that covers it; Phase 6
adds the real-hook fork evidence.

## The asset and the adversary

**Asset.** The equality between the price a user is shown and the price they receive.

**Adversary.** The author or operator of a Uniswap v4 hook. A hook is arbitrary code that
the `PoolManager` calls inside every swap on its pools, so the adversary can run any
computation, read any chain state, and return a delta that changes what the swapper gets.
They are assumed to be economically rational, able to redeploy and reconfigure at will,
and able to read this repository.

**Not in scope.** Compromise of the `PoolManager`, of the chain, or of the user's wallet;
token contracts that lie; ordinary MEV around the transaction rather than inside it.

## The core observation

`SwornRouter` probes and executes **inside one transaction**. Everything a hook can read
falls into exactly three buckets, and each is identical between the probe and the
execution by construction:

| What the hook can read                                                                                                                                                          | Probe vs execution | Why                                                                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Block and transaction environment — `tx.gasprice`, `tx.origin`, `block.coinbase`, `block.basefee`, `block.prevrandao`, `block.number`, `block.timestamp`, `gaslimit`, `chainid` | identical          | it is literally the same transaction                                                                                                                               |
| Chain state — its own storage, other contracts' storage, balances, `PoolManager` deltas and slots                                                                               | identical          | the probe reverts, and a revert rolls back state changes **and transient storage** (EIP-1153), so both calls start from the same state                             |
| Call context — `msg.sender`, `msg.data`, `gasleft()` at entry, call depth, `address(this)` of the caller                                                                        | identical          | the router makes the execution path byte-for-byte the same sequence of external calls as the probe: same self-call depth, same calldata, same explicit gas stipend |

There is no fourth bucket. A hook therefore cannot distinguish "being simulated" from
"being executed", because Sworn removed the distinction rather than trying to hide it.

**And if the enumeration is wrong**, the final assertion `executedDelta == probed[chosen]`
still holds: any residual difference reverts the transaction. The failure mode is denial,
never theft. That is the property the design actually rests on — the enumeration above
explains _why_ denial is rare, not why theft is impossible.

## Capabilities and coverage

| #   | Capability                      | How it works today                                                            | What Sworn does                                                                                                                                                                         | Fixture (Phase 5)                |
| --- | ------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| 1   | **Gas-price sniffing**          | `tx.gasprice == 0` implies `eth_call`; charge only when non-zero              | probe runs in the real transaction, so it sees the real gas price; the attractive quote is never produced                                                                               | `GaspriceSniffHook`              |
| 2   | **Origin / sender sniffing**    | honest when `tx.origin == address(0)` or a known simulator; toxic otherwise   | same — `tx.origin` is the real user in both calls                                                                                                                                       | `OriginSniffHook`                |
| 3   | **Coinbase / basefee sniffing** | simulators often leave `block.coinbase` zeroed                                | same                                                                                                                                                                                    | `CoinbaseBasefeeSniffHook`       |
| 4   | **Dice roll, block-sourced**    | fee from `prevrandao`/`blockhash` — no simulator can predict it               | identical in probe and execution (same block), so the probe shows the _true_ outcome and the router only picks the hook if it actually wins                                             | `DiceRollHook` (block variant)   |
| 5   | **Dice roll, counter-sourced**  | fee from a storage counter incremented per swap                               | the probe's revert rolls the counter back, so both calls see the same value                                                                                                             | `DiceRollHook` (storage variant) |
| 6   | **Owner switch**                | operator flips a `discountBps` between the quote and the fill                 | a state change cannot land _between_ probe and execution — they are in one transaction, and the attacker does not get a turn                                                            | `OwnerSwitchHook`                |
| 7   | **Router whitelisting**         | honest only for whitelisted `msg.sender`s                                     | if the hook is honest to Sworn, the user gets the honest price; if it is toxic to Sworn, the probe reveals it and the router routes elsewhere. Consistent behaviour is _safe_ behaviour | `RouterWhitelistHook`            |
| 8   | **Gas-left sniffing**           | infer simulation from an unusual `gasleft()`                                  | both calls get the same explicit `probeGas` stipend, so entry `gasleft()` is equal (see below)                                                                                          | `GasSniffHook`                   |
| 9   | **Callback probing**            | hook calls back into the router to look for a "probing" flag                  | the router exposes no phase flag in storage, transient storage or any view — anything a hook can call returns the same in both calls                                                    | `CallbackSniffHook`              |
| 10  | **Revert griefing**             | revert unless the environment looks like a simulation, wasting the user's gas | a probe revert is caught and the candidate is marked `UNAVAILABLE`; the swap proceeds on another route                                                                                  | `RevertGriefHook`                |
| 11  | **Anything not listed**         | —                                                                             | `executedDelta == probed[chosen]` reverts with `Divergence(...)`. Theft is impossible; griefing costs the hook its route                                                                | fuzz + invariant tests           |

## The gas stipend, precisely

EIP-150 forwards at most `63/64` of the remaining gas to a subcall, so "give both calls
the same gas" is not automatic. `SwornRouter` passes an **explicit** stipend `probeGas` to
both the probe self-call and the execution self-call. That stipend is honoured exactly as
long as `probeGas ≤ 63/64 × gasleft()` at each call site, which is why:

- the router checks the inequality before the execution call and reverts with a dedicated
  error rather than silently forwarding less;
- `probeGas` is a caller-supplied parameter, so an integrator can size it for the route;
- the invariant "hook observes equal `gasleft()` at entry in probe and execution" is a
  test (`GasSniffHook`), not a comment.

## What Sworn does not protect against

- **Harm to liquidity providers.** A hook can be scrupulously honest to swappers and still
  extract from LPs. Nothing here measures or prevents that.
- **A uniformly bad price.** If every candidate is bad, Sworn executes the best available
  one or reverts on `minOut`. It guarantees _quote integrity_, not _good pricing_.
- **Bad candidate sets.** Sworn selects among the candidates it is given. An integrator
  that passes one toxic pool gets the guarantee that the price is real, and nothing more.
  The SDK deriving candidates from the index (Phase 8) is what makes the set adversary-independent.
- **Griefing as a denial of service.** A hook that reverts for everyone makes its own pool
  unroutable. Users are safe; the pool is simply useless. Sworn converts theft into
  denial — an improvement, not an elimination.
- **Off-path extraction.** Sandwiching, backrunning and other MEV outside the swap call.
- **Hook upgrades between transactions.** A proxy hook honest today can be toxic tomorrow.
  Within any single transaction the guarantee holds; across transactions it is why
  `UPGRADEABLE` is a scored flag rather than a fatal one.

## "Nondeterminism Sworn cannot roll back"

There is none _inside a transaction_, and the reason is worth stating precisely rather
than asserting: the EVM's execution of a transaction is a pure function of
(block header, transaction, pre-state). The probe and the execution share the block
header and the transaction. The revert of the probe restores the pre-state exactly —
EIP-1153 makes transient storage revert-sensitive for exactly this class of reason, and
without that guarantee a hook could count probe invocations in transient storage and the
model would break. Under those conditions, different outputs require different inputs, and
the only remaining input is call context, which the router holds fixed.

The honest caveat: this argument is about the EVM as specified. It relies on
`evm_version = cancun` semantics and on the router genuinely holding call context fixed,
which is a property of the implementation and therefore a matter for tests — Phase 5 —
rather than for prose.
