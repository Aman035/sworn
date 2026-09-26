# Feedback on building with Uniswap v4

I built [Sworn](README.md) — a router that verifies hook behaviour inside the transaction
that settles — over about a week. This is what cost me time, roughly in the order it cost
it. Everything here has something in the repo behind it.

## Time to first success

About four hours from an empty directory to a swap going through my own router against a
locally deployed `PoolManager`. Maybe 45 minutes of that was reading `Hooks.sol` and the
delta accounting, which were fine. The rest was toolchain.

Two things ate that afternoon, and neither is about v4's design. One was the compiler
settings, below. The other was my own fault but worth mentioning: v4-core's default test
liquidity is about 6e15 per side, so my first "the router is broken" bug was actually a
1e18 swap draining the pool to its price limit. Every number I got back was an artefact of
the fixture. A line in the testing docs about sizing swaps against `Deployers`' default
liquidity would have saved me an hour of staring at correct code.

## Friction, in order of cost

### `optimizer_runs` is load-bearing and nothing says so

I set `optimizer_runs = 800` with `via_ir = true` on solc 0.8.26, which is a boring
default, and `PoolManager` would not compile:

```
Error: Yul exception: Variable memPtr_1 is 1 too deep in the stack
```

That error names a Yul internal and gives you nothing to search for. I went looking for a
bug in my own contracts first. The fix is that v4-core's own `foundry.toml` uses
`optimizer_runs = 44444444` and you have to match it — it is effectively a hard
requirement for compiling core, and I could not find it stated in any integration guide.

Either put the required compiler settings in the integration docs, or fail with a message
that points at them.

### `v4-periphery` has no tags, and its `main` does not build against core's

This was the single biggest avoidable cost of the whole setup.

`v4-periphery` publishes no release tags, so you pin an arbitrary `main` commit and hope.
Worse, that `main` is built against a later `v4-core` than the `v4.0.0` tag: `SwapParams`
and `ModifyLiquidityParams` have moved out of `IPoolManager` into `types/PoolOperation.sol`,
so `V4Quoter` will not compile against released core.

You cannot keep both. If you do, the compiler has two distinct `IPoolManager` types and a
`PoolKey` built from one cannot be passed to a quoter built from the other — which is a
confusing error to read at 1am. I gave up on the release tag and pinned the same core
commit periphery pins.

While I am here: `permit2`'s only git tag is its deployed address string, which is not a
version.

Tagging periphery releases, and saying which core each one builds against, would fix this.

### The `Swap` event's natspec has the sign backwards

`IPoolManager.sol` says:

```solidity
/// @param amount0 The delta of the currency0 balance of the pool
```

but `PoolManager.sol:241` emits `delta.amount0()`, which is the _swapper's_ delta — the
opposite sign. Build an indexer from the docs and every fill comes out backwards, silently,
because the amounts still look plausible. I only settled it by reading the emission site.

One-line fix, prevents a whole class of downstream error.

### You cannot measure what a hook took from the `Swap` event at all

This is the same event and a much worse problem, and it is the finding I would most want
someone at Uniswap to read.

`PoolManager.swap` emits `Swap` **between** `beforeSwap` and `afterSwap`:

```solidity
(amountToSwap, beforeSwapDelta, lpFeeOverride) = key.hooks.beforeSwap(key, params, hookData);
swapDelta = _swap(pool, id, ...);     // emits Swap(amount0, amount1)
(swapDelta, hookDelta) = key.hooks.afterSwap(key, params, swapDelta, hookData, beforeSwapDelta);
_accountPoolBalanceDelta(key, swapDelta, msg.sender);
```

The ordering is deliberate and the code says so. What is not documented is the
consequence: the event's amounts exclude anything the hook takes in `afterSwap`. For a
delta-returning hook they are neither the swapper's input nor their output.

Here is one hook on Base taking exactly 1% there:

```
Swap event amount1      3,941,355,102,139,778,949
swap() return value     3,901,941,551,118,381,160
                        ───────────────────────────
difference                 39,413,551,021,397,789   = 1.00%
```

Read from the event, that hook looks like it is handing users an extra percent. It is
charging them one.

I lost most of a day to this. My pipeline was reporting a systematic −101 bps "take"
across unrelated hooks — users apparently getting _more_ than they were quoted. I checked
fee tiers first, which was wrong; hooks on fee-0 pools showed the same offset. Then I
built a whole `hookData` recovery module on the theory that I was quoting hooks with the
wrong calldata, which was also wrong — `hookData` is non-empty on 4.4% of swaps. Then I
read `PoolManager.swap` line by line and found the emission order.

The general version of this: **anything built on `Swap` events under-reports exactly the
hooks that take the most**, because taking in `afterSwap` is invisible there. And building
on the event is the obvious thing to do — it is what I did.

There is a smaller sibling bug in the same event: the sign pattern cannot tell exact-input
on token0 from exact-output on token1. They are identical. 13% of the fills I had
classified as exact-input from the event turned out to be exact-output, which means I was
re-quoting a swap that never happened.

Both are recoverable from `debug_traceTransaction` — calldata for `amountSpecified` and
`hookData`, return value for the real delta. It works, and costs about 0.01s per
transaction. But it needs an archive node with the debug namespace, which puts honest
measurement out of reach of anyone working from logs.

Two ways out, either would do:

1. Document on `IPoolManager.Swap` that the amounts are pre-`afterSwap` and are not what
   the swapper received, and point at where to get that instead.
2. Better, emit the caller's final delta — a `SwapSettled(id, sender, amount0, amount1)`
   after `_accountPoolBalanceDelta`, or an `afterSwap` delta field on the existing event.

Without one of those, "how much did this hook charge" is not answerable from logs, which
seems like a strange place to be when hooks are the headline feature.

### Reading the logs at all is a research project

None of this is Uniswap's fault, but it was the dominant cost of everything data-driven I
did, and a first-party feed would erase it.

Pulling one 30-day census I hit five different failures that look similar and need
opposite responses: a `413` on response size (shrink the window), Alchemy's 10-block
`eth_getLogs` cap on the free tier (shrink, or pay), a `429` (wait — do _not_ shrink, or
you make it worse), a `503` mid-pull (retry, do not shrink), and `failed to get logs for
block #N`, which for one Polygon block was simply permanent.

Conflate any two of those and you either corrupt the data or burn an hour. I lost a
10.6%-complete BNB census to a single 503 before I handled them separately.

A published, paginated feed of `PoolManager` events would let integrators skip all of it.

### Address-encoded permissions are great; the tooling around them is thin

Deriving permissions from the hook address is a genuinely good design. Capability checks
are free and unforgeable, and I checked the decoding against all 4,961 hooklist entries
with zero disagreements.

What is missing is the inverse: given an address, a one-call way to get its permissions
outside Solidity. Everyone re-implements the bit decoding. Publishing it as a small SDK
helper, and including decoded permissions in `hooklist.json`, would cost almost nothing.

## The missing capability

**A hook has no way to prove it behaves, and a router has no cheap way to find out.**

`hooklist` records provenance — name, deployer, verified source, upgradeability — and
nothing about behaviour. The predictable result is that routers who get burned drop hooked
pools wholesale, which punishes exactly the builders you want. On Base 98.5% of pools
carry a hook, so "avoid hooks" is not a strategy anyone can actually adopt.

Some numbers from the census that I did not expect:

- 69,242 distinct hooks on Base, 15.1% of them upgradeable
- 99.2% contain an environment opcode, so a presence-based detector flags nearly the whole
  chain and is useless
- only 38.3% contain one that could actually distinguish a simulation, and tracing shows
  most of those never execute it while pricing
- `ORIGIN` shows up in 35.4% of hooks; `GASPRICE`, the textbook spoofing signal, in 0.3%

A detector tuned for the textbook attack would miss almost everything. That is why I
stopped trying to detect.

## The one improvement with the greatest impact

**Put behavioural fields in the hooklist schema and expose them in the Trading API.**

Three would be enough: `divergenceScore`, `envSensitive`, `intermittent` — each with the
block it was measured at and a hash of the dataset behind it, so a reader can re-derive
the number instead of trusting it. I publish exactly that shape on-chain in `HookBook`
(`0x8A4470f7DDa8525b484527b21B19c3bc876A04c3`, Base Sepolia), and the generator that fills
the hooklist fields from it is in [docs/HOOKLIST_PROPOSAL.md](docs/HOOKLIST_PROPOSAL.md).

One detail I would insist on, having got it wrong first: **an absent score must not read
as a good one.** If unmeasured and measured-clean look the same, the cheapest path to a
perfect rating is to deploy and never trade. `HookBook` returns `INSUFFICIENT_DATA`
instead of 0, and the SDK refuses unscored hooks when you ask for a ceiling.

And the honest limit of the idea, since I would rather say it than have someone point it
out: reputation lags, and a hook can flip between transactions. Enso saw a pool toxic for
423 of 718 hours, switching 26 times. No registry refreshed on human timescales tracks
that. Scores make honesty legible; only verifying inside the transaction makes lying
unprofitable. You want both, and neither replaces the other.

## What worked well

**Address-encoded permissions**, as above — unforgeable, free to check, and correct in
every one of the 4,961 entries I tested.

**Flash accounting.** Probing several routes inside one `unlock` and letting the losing
probes revert is natural in v4. The same thing in v3 would have been miserable.

**Transient storage.** EIP-1153's revert semantics are the reason Sworn's guarantee holds
at all: a hook cannot count how many times it has been probed, because the probe's revert
rolls back its own bookkeeping. That is tested in `test_gasSniff_probeStateIsRolledBack`,
and it is the single nicest thing about building this on v4 rather than anywhere else.

**`vm.rollFork(txHash)`.** Re-quoting a settled fill against the state immediately before
it is one cheatcode, and every measured number in this repo rests on it.
