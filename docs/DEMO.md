# Demo

```bash
./scripts/demo.sh
```

No manual steps, no pre-recorded output. Every figure the script prints is produced by the
EVM during the run. There is no narration string in
[`Demo.t.sol`](../contracts/test/unit/Demo.t.sol) that contains a number, because a demo
whose numbers are typed in is a slideshow.

The demo is written as a **test**, so it cannot rot. If the story stops being true, CI
fails.

## The three acts

Ordered by how hard each is to fake.

### Act 1: the spoof, on a local chain (~20 s)

`forge test --match-contract DemoTest -vv`

Two pools for the same pair: one hookless, one hooked by `GaspriceSniffHook`, a fixture
that reads `tx.gasprice` and charges only when it is non-zero. Exactly the branch that
distinguishes `eth_call` from a transaction.

| Beat | What is shown                                        | Why it matters                                                |
| ---- | ---------------------------------------------------- | ------------------------------------------------------------- |
| 1    | Both pools exist for the same pair                   | The router has a real choice                                  |
| 2    | `tx.gasprice = 0` → the pool quotes well             | This is the number every router sees                          |
| 3    | `tx.gasprice = 1 gwei` → the pool delivers ~18% less | This is the number the user gets                              |
| 4    | Naive router vs `swornSwap` on the same state        | Sworn recovers the difference                                 |
| 5    | `HookBook` on a scored hook and on an unseen one     | Unmeasured reads as `INSUFFICIENT_DATA`, never as a clean `0` |

Beat 4 is the mechanism. The probe runs in the same transaction at the same
`tx.gasprice`, so the hook has no branch left to take: it cannot answer the probe honestly
and the execution dishonestly, because they are the same call.

The assertions are the story. `assertGt(swornOut, naiveOut)` is what makes this a demo
rather than a claim.

### Act 2: the same router against real Base hooks (~60 s)

`anvil --fork-url $BASE_RPC_ARCHIVE --fork-block-number 51700000`, then
[`RealSwap.fork.t.sol`](../contracts/test/fork/RealSwap.fork.t.sol) against the local node.

Act 1 uses a fixture that is _designed_ to lie, which is the right way to show the
mechanism and the wrong way to claim it works in production. So act 2 routes ETH → USDC
through hooks that are live on Base right now and asserts the harder thing:

- the swap **completes** and pays out;
- the USDC actually received equals the amount the router reported;
- the divergence check held, so the probe matched the execution on real hook code.

It runs on anvil rather than against the provider directly so the chain is still there
afterwards. You can poke at it, replay the swap, change the amount.

> **A tooling limit worth knowing about.** A large family of Base tokens (vanity addresses of the form `0xb2…01`) return a
> one-byte `0xef` from `eth_getCode`, which is the EOF prefix rather than runnable bytecode.
> On chain they work normally: supply, decimals, and thousands of `Transfer` logs. Inside a
> Foundry fork they do not, because forge fetches code with `eth_getCode`, receives `0xef`,
> and executing that is an invalid opcode. A swap into one settles on mainnet and reverts on
> a fork with `OpcodeNotFound` four frames down, inside `transfer`.
>
> That is a tooling limitation, not a broken token, and it constrains which measured fills
> can be replayed in a fork test at all.

### Act 3: the dashboard (~30 s)

Builds `app/` and serves the static export. Every figure renders from the same
`data/results/*.json` the README does, with a provenance rail showing the snapshot hash and
block range behind each panel.

## What the demo does not show

- **A divergent hook caught live.** Act 2 routes through real hooks, but none of the pools
  it uses was measured as divergent; the swap completing is the claim, not a catch.
- **Mainnet `HookBook`.** Scores are published to Base Sepolia. The mainnet registry is
  deployed by the same script and needs only funding.
- **The full analysis.** The pipelines take hours over a 30-day window and are gated
  separately. `make phase-3`, `make phase-6`. The demo consumes their output.

## Recording it

```bash
asciinema rec sworn-demo.cast -c ./scripts/demo.sh
```

Or any screen recorder. Keep act 1's output on screen long enough to read the two numbers
in beats 2 and 3 side by side: that contrast is the entire argument, and it is the one
thing a viewer should leave with.
