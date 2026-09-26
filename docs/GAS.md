# Gas

What the guarantee costs, measured rather than estimated.

## Probe overhead

From `SwornGasTest`, against `NaiveRouter`: a slippage-only router that does what a
competent router does today. All pools honest, so these are pure routing overhead with no
hook behaviour mixed in.

| Route                           |     Gas | Overhead vs naive |
| ------------------------------- | ------: | ----------------: |
| `NaiveRouter`, 1 pool, no probe | 111,553 |. |
| `swornSwap`, 1 candidate        | 204,270 |           +92,717 |
| `swornSwap`, 2 candidates       | 275,159 |          +163,606 |
| `swornSwap`, 3 candidates       | 341,845 |          +230,292 |

Each additional candidate costs about **68,000 gas**, and the cost is linear. Asserted by
`test_overheadScalesLinearlyInCandidates`. That is the design: one more candidate is one
more probe, not a re-run of the route.

The first candidate is the expensive one (+92,717) because it pays for the probe machinery
itself: an extra `unlock` frame, the self-call, and the delta comparison. After that each
probe is just another swap that reverts.

## In money

Base fees move, so these are computed from observed values rather than fixed here. At the
gas price measured on Base Sepolia while deploying (0.006 gwei) and an ETH price of
$3,000:

| Candidates |     Gas | Cost on an L2 at 0.006 gwei |
| ---------- | ------: | --------------------------: |
| 1          | 204,270 |                     $0.0037 |
| 2          | 275,159 |                     $0.0050 |
| 3          | 341,845 |                     $0.0062 |

On an L2 the guarantee costs fractions of a cent, and the overhead alone is under a
third of a cent for three candidates. Against a spoofing hook taking 18% of a $1,000 swap. $180: the trade is not close.

L1 is a different calculation. At 20 gwei and $3,000 ETH, three candidates cost about
$20.51 against a naive router's $6.69, so the $13.82 of overhead only pays for itself on
trades where 18% exceeds it. Roughly $77 and up. On Ethereum mainnet the sensible
defaults are fewer candidates and a `maxScore` pre-filter to skip probing hooks already
measured as bad.

## Why the overhead is what it is

A probe is a real swap: it moves the pool, computes the hook's behaviour, and then reverts.
There is no cheaper way to learn what a hook will actually do, because anything cheaper is
a simulation, and a simulation is exactly what the hook lies to.

The alternatives and what they cost instead:

| Approach                 |          Gas | What it buys                                                                         |
| ------------------------ | -----------: | ------------------------------------------------------------------------------------ |
| Slippage bound only      |      111,553 | nothing against a hook; `minOut` cannot tell "the market moved" from "the hook lied" |
| Off-chain quote + trust  |      111,553 | nothing; this is the attack surface                                                  |
| Allowlist lookup         |     ~114,000 | per-hook reputation, always one toggle behind                                        |
| **Probe in-transaction** | **204,270+** | the executed amount equals the probed amount, or the transaction reverts             |

## Reproducing

```bash
cd contracts && forge test --match-contract SwornGasTest -vv
```

The numbers above come from that test at the commit recorded in `PHASES.md` for Phase 5.
Per-chain USD figures against live base fees are Phase 6's remaining work.
