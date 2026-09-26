# Hooklist: carry behaviour, not only identity

A proposal for [Uniswap/hooklist](https://github.com/Uniswap/hooklist), with data.

## The gap

The hooklist describes a hook by **who made it** — deployer, verified source, audit link —
and by the **static permissions** encoded in its address. Both are checkable and both are
useful. Neither answers the question an integrator turning on hooks-inclusive routing is
actually asking: _what does this hook do to my users?_

Two specific failures follow:

1. **Listing is permanent; bytecode is not.** 10,430 of the 69,242 hooks on
   Base sit behind a proxy. An address-keyed allowlist cannot express that a listed hook
   changed after it was listed. Of the 25 hooks measured here, 0 are
   upgradeable — a fact about which hooks carry the most volume, not a reason to drop the
   field.
2. **Permissions are capability, not behaviour.** `beforeSwapReturnsDelta` says a hook
   _can_ alter the amounts. Almost every interesting hook has it. It says nothing about
   whether the hook charges more than it quoted.

## Proposed fields

Added under `properties`, all optional, all absent-means-unknown:

| Field                 | Type              | Why                                                                                                                                                                                                                                      |
| --------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `divergenceScore`     | `integer or null` | 0 (clean) to 100 (avoid), or null when too few fills have been measured to say. Null rather than 0, so an unmeasured hook can never be mistaken for a clean one.                                                                         |
| `divergenceAsOfBlock` | `integer`         | The block the measurement describes. A score with no block is a score with no shelf life, and hooks change.                                                                                                                              |
| `divergenceSnapshot`  | `string`          | sha256 of the dataset the score was computed from, so a reader can re-derive the number instead of trusting it.                                                                                                                          |
| `envSensitive`        | `boolean`         | The hook executes an environment read (`GASPRICE`, `ORIGIN`, `COINBASE`, `NUMBER`, `PREVRANDAO`) on the swap path. Attributed by call-stack, so a read made by a library the hook calls still counts and a read made elsewhere does not. |
| `intermittent`        | `boolean`         | The hook's charged rate crosses the threshold in some hours and not others. A one-shot review of an intermittent hook is a coin flip.                                                                                                    |
| `upgradeable`         | `boolean`         | Already partly implied by `deployer`, but stated directly: today's bytecode is not tomorrow's, and listing is permanent while code is not.                                                                                               |

The critical convention is that **absence and zero are different**. `divergenceScore: null`
means nobody has measured this hook; `divergenceScore: 0` means somebody measured it and
found nothing. A schema that cannot tell those apart turns "unreviewed" into "safe", which
is the failure mode an allowlist is supposed to prevent.

## Worked sample

`data/results/hooklist_proposal.json` carries these fields for every hook this repo has
measured: 25 hooks on Base, with 1 executing an environment read on the swap
path. The highest score is 40, at `0x0469a4bd3724dc86c9542f4694c976da13c450c0`.

```json
[
  {
    "address": "0x0469a4bd3724dc86c9542f4694c976da13c450c0",
    "chain": "base",
    "divergenceScore": 40,
    "divergenceAsOfBlock": 51778292,
    "divergenceSnapshot": "0xa5379268608d769898a5e9a90b37270978167c233a24381dc307a7b1adfc3205",
    "envSensitive": true,
    "intermittent": false,
    "upgradeable": false
  },
  {
    "address": "0x1f91c998e7c2f4b690d75bdbf6502bdcd6e02acc",
    "chain": "base",
    "divergenceScore": 24,
    "divergenceAsOfBlock": 51778292,
    "divergenceSnapshot": "0xa5379268608d769898a5e9a90b37270978167c233a24381dc307a7b1adfc3205",
    "envSensitive": false,
    "intermittent": false,
    "upgradeable": false
  },
  {
    "address": "0xf54473f4c554baa8411c0a7dac7df735f34d00c4",
    "chain": "base",
    "divergenceScore": 24,
    "divergenceAsOfBlock": 51778292,
    "divergenceSnapshot": "0xa5379268608d769898a5e9a90b37270978167c233a24381dc307a7b1adfc3205",
    "envSensitive": false,
    "intermittent": false,
    "upgradeable": false
  }
]
```

## Where the values come from

| Field                 | Source                                                                   |
| --------------------- | ------------------------------------------------------------------------ |
| `divergenceScore`     | `data/results/scores.json`, specified in [SCORING.md](SCORING.md)        |
| `divergenceAsOfBlock` | the block of the fills snapshot the score was computed over              |
| `divergenceSnapshot`  | sha256 of that snapshot, recorded in the result's `meta`                 |
| `envSensitive`        | `data/results/probe.json`, `debug_traceCall` with call-stack attribution |
| `intermittent`        | `data/results/intermittency.json`, hourly charged rate over 30 days      |
| `upgradeable`         | `data/results/census.json`, proxy detection from bytecode                |

The same values are published on-chain by [`HookBook`](../contracts/src/HookBook.sol), so a
generator can fill this section of the hooklist from a contract call rather than from a
file anyone can edit — and `HookBook` already refuses to report an unmeasured hook as
clean, returning `hasScore() == false` and `INSUFFICIENT_DATA` instead of a zero.

## What this proposal does not claim

- **These scores are not authoritative.** They come from one team's measurement over a
  30-day window on one chain. The point of `divergenceSnapshot` is that you do not have to
  take them on trust.
- **A score is not a guarantee.** It describes what a hook did, not what it will do next
  block. That is why this repo's actual answer is a router that verifies in-transaction;
  the score only hints at which candidates are worth probing.
- **The measurement has a floor.** Roughly half the charged fills in the underlying sample
  are measurement error, quantified and published in `divergence.noise_floor`.
