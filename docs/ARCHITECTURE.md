# Architecture

> Skeleton. Phase 1 fills in components, data flow and RPC requirements; Phase 0 only
> records the pinned toolchain and dependencies so builds are reproducible from day one.

## Pinned dependencies

Solidity dependencies are git submodules under `contracts/lib/`. `make install` runs
`git submodule update --init --recursive`.

| Dependency | Pin | Why |
| ---------- | --- | --- |
| `foundry-rs/forge-std` | `v1.9.7` | test harness, cheatcodes |
| `Uniswap/v4-core` | `v4.0.0` (`e50237c`) | `PoolManager`, `Hooks`, `PoolKey`, delta accounting |
| `Uniswap/v4-periphery` | `9969eec` (no release tags exist) | `V4Quoter`, `BaseHook`, router base classes |
| `Uniswap/permit2` | `cc56ad0` (only tag is the deployed address) | `permitTransferFrom` path in `SwornRouter` |
| `Uniswap/universal-router` | `v1.6.0` — **referenced, not vendored** | read-only reference for the Phase 11 UR-compatible entrypoint |

`v4-core` transitively pins `solmate` and `openzeppelin-contracts`; both are remapped
through `contracts/lib/v4-core/lib/` so there is exactly one copy of each in the build.

## Toolchain

| Tool | Version | Notes |
| ---- | ------- | ----- |
| Foundry | `forge 1.5.1-stable` | solc `0.8.26`, `evm_version = cancun`, `via_ir = true`, optimizer 800 |
| Node | `>= 20` (CI: 20) | pnpm `9.15.3` workspaces |
| TypeScript | `5.7.3` | strict, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` |
| Python | `>= 3.11` (CI: 3.11) | pandas / pyarrow / duckdb, pinned exactly in `analysis/pyproject.toml` |

`evm_version = cancun` is required: v4 uses transient storage (`TSTORE`/`TLOAD`) for its
lock and delta accounting, and `SwornRouter`'s unlock guard does the same.

## Chains

Build priority, matching `analysis/config.yaml`:

| Chain | ID | Why this order |
| ----- | -- | -------------- |
| Base | 8453 | highest v4 hook activity; the named 0x hook lives here |
| BNB | 56 | second named 0x hook |
| Arbitrum | 42161 | volume |
| Unichain | 130 | Uniswap's own chain |
| Ethereum | 1 | L1 reference, worst-case probe gas |
| Polygon | 137 | the Enso report's hook |

## Components

_Phase 1._ Component diagram, data flow (index → analysis → results → attestor →
`HookBook` → SDK/app), and the RPC capability matrix (archive state, `eth_getLogs`
ranges, `debug_traceCall`).
