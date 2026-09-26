# SWORN. Build Plan for Claude Code

> **Sworn**: execution-integrity for Uniswap v4. Toxic hooks quote one price to simulators and deliver another at execution. Sworn (1) measures that gap across every hooked pool on every chain, continuously; (2) makes it impossible to exploit by moving the quote _inside_ the transaction and selecting the route at execution time; (3) publishes on-chain attestations that wallets, aggregators and agents can read in one call.
>
> This file is the single source of truth for Claude Code. Work strictly phase by phase. A phase is **not done** until its exit gate passes (`make phase-N`) and `PHASES.md` is updated with the evidence. Never skip a gate. Never fabricate a number: every figure in docs must be produced by a script in this repo and reproducible from a pinned data snapshot.

---

## 0. The story we are building toward

Everything in this repo exists to make five claims true and demonstrable. Keep them in front of you.

1. **The protocol assumes quote == execution and never enforces it.** A v4 hook is arbitrary code that runs inside every swap. Routers, wallets and agents price routes with `eth_call`. A hook can read `tx.gasprice`, `tx.origin`, `block.coinbase`, `block.basefee`, or roll dice, and behave honestly for the simulator and dishonestly for the user. Uniswap's own answer today is allowlists (hooklist + UniRoute). Aggregators' answer is proprietary detection (0x, Enso). Nobody has a _per-transaction guarantee_.
2. **Measured on mainnet, the gap is large and intermittent.** We reproduce, openly and continuously, what 0x (Sept 14 2026: 84,163 hooks, 19.4% safe / 54.2% malicious / 26.4% likely malicious; fills delivering up to 50% less than quoted) and Enso (July 16 2026: a Polygon hook with a ~98.9% fee above a gas-price threshold, a Curve pool toxic ~59% of observed hours with its switch toggled 26 times, MetaMask routing ~$5.88M through it) reported with closed tooling. Our numbers are ours, per hook, per hour, per front-end, reproducible.
3. **The fix is a routing primitive, not a blacklist.** `SwornRouter` probes every candidate pool _inside the real transaction_ (same env, state rolled back), compares real outputs, executes the best one, and asserts the executed delta equals the probed delta. Spoofing becomes structurally impossible; toxic pools lose both extraction and revert-griefing.
4. **Honesty becomes attestable.** `HookBook` publishes per-hook divergence scores and flags on-chain, refreshed by an attestor. Honest hook builders get a way to _prove_ honesty so routers stop delisting them wholesale.
5. **This is a product, not a demo.** Wallets, aggregators and agent frameworks carry reimbursement and liability risk for every quote they show. Sworn sells the guarantee (router), the data (index/attestations), and the certification (hook developers).

The README's final structure is fixed (see Phase 10). Build so that each README section is backed by code, tests and data in this repo.

---

## 1. Operating rules for Claude Code

- **Phase gating.** Do not start Phase N+1 until `make phase-N` exits 0 _and_ `PHASES.md` has a `DONE` entry for Phase N with: commit hash, date, gate output summary, and the artifacts produced. If a gate cannot pass, write a `BLOCKED` entry with the exact failure and stop; do not paper over it.
- **No mocks where reality is available.** Analysis runs against real chain data. Contract tests run against forked mainnets for anything involving real hooks. Unit tests may use fixtures; the _story_ may not.
- **No fabricated numbers.** Any number in `README.md`, `docs/`, or the dashboard must be emitted by a script into `data/results/*.json` and rendered from there. Until computed, write `TBD(phase-N)`.
- **Reproducibility.** Every dataset gets a `data/snapshots/<name>/MANIFEST.json` with chain, block range, RPC provider, script commit, row counts and a sha256 of the parquet/CSV. Results reference the snapshot they came from.
- **Git hygiene.** Small, descriptive commits, continuous from day one (the Uniswap prize explicitly rejects single-commit repos). Conventional commit prefixes: `feat:`, `fix:`, `test:`, `data:`, `docs:`, `chore:`.
- **Secrets.** RPC keys, Etherscan keys, attestor private key only via `.env` (gitignored). Provide `.env.example`. CI uses repository secrets.
- **Toolchain.** Foundry (Solidity 0.8.26, via-IR on), Node 20 + pnpm, TypeScript strict, Python 3.11 (pandas/pyarrow/duckdb), Ponder for indexing, Next.js for the dashboard. Pin every dependency.
- **Chains (priority order).** Base (8453), BNB (56), Arbitrum (42161), Unichain (130), Ethereum (1), Polygon (137). Base and BNB first: that's where 0x's named hooks live.
- **Naming.** Contracts: `SwornRouter`, `HookBook`, `SwornAttestor` (off-chain), `hook-probe` (kit), `sworn-sdk`, `sworn-index`, `sworn-app`. Toxic fixtures live under `contracts/test/fixtures/`.
- **When unsure about a v4 internal, read the source in `lib/v4-core` and `lib/v4-periphery`, write a test that proves the behavior, then proceed.** Do not guess.

Repository layout (create in Phase 0):

```
sworn/
  PHASES.md                     # gate ledger (status, evidence, commit)
  Makefile                      # make phase-N targets
  contracts/                    # Foundry
    src/SwornRouter.sol
    src/HookBook.sol
    src/libraries/*.sol
    test/unit/*.t.sol
    test/fork/*.t.sol
    test/fixtures/*.sol         # ToxicHook variants, HonestHook
    script/*.s.sol
  index/                        # Ponder app (census, fills, scores, sworn executions)
  analysis/                     # Python: pipelines A–F
    pipelines/
    notebooks/
    lib/
  probe/                        # hook-probe kit (TS): static, differential, trace
  attestor/                     # scheduled scoring + HookBook writer (TS)
  sdk/                          # sworn-sdk (TS): build calldata from quotes; viem action
  app/                          # Next.js dashboard
  data/
    snapshots/                  # raw pulls + MANIFEST.json (git-lfs or pointer files)
    results/                    # computed JSON consumed by README/app
  docs/
    STORY.md
    METRICS.md
    THREAT_MODEL.md
    ARCHITECTURE.md
    phases/PHASE-N.md
  FEEDBACK.md
  README.md
```

---

## 2. Phase plan

Each phase: **Objective → Tasks → Artifacts → Gate (tests/checks) → Exit criteria → Pitfalls.**

### Phase 0. Bootstrap, conventions, gating

**Objective.** A repo where every later phase can be checked mechanically.

**Tasks.**

1. Initialize monorepo per layout above. `pnpm` workspaces for TS packages; Foundry in `contracts/`; Python env in `analysis/` (`pyproject.toml`, `uv` or `poetry`).
2. Install v4 deps as git submodules pinned to release tags: `Uniswap/v4-core`, `Uniswap/v4-periphery`, `Uniswap/permit2`, `Uniswap/universal-router` (read-only reference). Record tags in `docs/ARCHITECTURE.md`.
3. `Makefile` with `phase-0 … phase-11` targets; each runs that phase's checks and appends a machine-readable line to `PHASES.md` only on success (`scripts/mark-phase.sh N`).
4. GitHub Actions: `ci.yml` (lint, unit tests, TS typecheck, python tests), `fork.yml` (fork tests, needs `BASE_RPC`, `BNB_RPC` secrets), `attestor.yml` (scheduled; disabled until Phase 7).
5. `.env.example` with `BASE_RPC_ARCHIVE`, `BNB_RPC_ARCHIVE`, `ARB_RPC_ARCHIVE`, `UNI_RPC_ARCHIVE`, `ETH_RPC_ARCHIVE`, `POLYGON_RPC_ARCHIVE`, `ETHERSCAN_KEYS`, `ATTESTOR_PK`, `DASHBOARD_DB_URL`.
6. `docs/phases/PHASE-0.md` template; copy for each phase.

**Gate (`make phase-0`).** `forge build` succeeds with a trivial contract; `pnpm -r typecheck` passes; `pytest` collects at least one passing test; CI workflows validate (`act` dry-run or `actionlint`); `scripts/mark-phase.sh` refuses to mark a phase whose checks failed (test it by forcing a failing target).

**Exit criteria.** All above green; `PHASES.md` shows `Phase 0: DONE`.

---

### Phase 1. Story, sources, metric definitions

**Objective.** Freeze what we are measuring and why, before touching data. This prevents drifting numbers later.

**Tasks.**

1. `docs/STORY.md`: the five claims from §0, each with the external evidence that motivates it and the internal artifact that will prove it (table: claim → source → our artifact → phase).
2. `docs/SOURCES.md`: the external reports we reference (0x "Uniswap v4 hooks were a mistake", Enso "Toxic Pools", the hackmd consolidated impact report Enso links, Uniswap hooklist repo and schema, Uniswap "Access msg.sender inside a hook" guide, Uniswap Trading API `hooksOptions`). For each: URL, date, the exact figures we cite, and a note that we _reproduce_ rather than _reuse_ their numbers.
3. `docs/METRICS.md`. Precise definitions:
   - **Expected output** of a fill: output of the identical swap (same pool, same direction, same `amountSpecified`, same `sqrtPriceLimitX96`, same `hookData`) evaluated against the pool state immediately _before_ the fill's transaction. Primary method: Foundry `vm.rollFork(txHash)` (state after all prior txs in the block) + `V4Quoter`. Secondary (cheap) method: quote at block `N-1` end state; flagged `approx=true`.
   - **Realized output**: from the `Swap` event deltas of the fill.
   - **Shortfall** = `(expected − realized) / expected`. **Take** = shortfall in bps, positive means user got less.
   - **Nominal fee**: pool's LP fee for static-fee pools; for dynamic-fee pools (`fee == 0x800000`), the fee emitted in the `Swap` event.
   - **Excess take** = take − nominal fee (≥ 0 clipped). This is the "hook take" we attribute to hook behavior.
   - **Charged fill**: excess take > 5 bps (parameter, document sensitivity).
   - **Divergent hook**: any hook with ≥ 20 fills and ≥ 5% charged fills, or median charged excess take ≥ 100 bps. (Parameters live in `analysis/config.yaml`; report sensitivity in Phase 3.)
   - **Env-sensitive**: differential probes disagree beyond 1 bps, or trace shows env opcodes on the swap path.
   - **Intermittent**: hook's hourly charged-fill rate crosses the "charged" threshold ≥ 3 times in 30 days.
   - **Front-end attribution**: `Swap.sender` → router → product mapping table (`analysis/data/routers.csv`, hand-curated with sources).
   - **Protected value (Sworn replay)**: for a charged fill, `max(0, fallbackOutput − realized)` where `fallbackOutput` is the output of the best hookless pool for the same pair at the same state, minus estimated probe gas in output-token terms.
   - **Divergence score (0–100)** formula and its inputs (charged rate, median excess, intermittency, env-sensitivity, owner switches, upgradeability, revert-gating), with weights in config and a worked example.
4. `docs/THREAT_MODEL.md` (first draft): attacker capabilities (env sniffing, dice-roll, owner switch, sender-based whitelisting incl. whitelisting _our router_, gas-left sniffing, callbacks into the router, revert-griefing), what Sworn guarantees against each, what it cannot (a hook honest to everyone but bad for LPs; nondeterminism sourced from state Sworn cannot roll back. There is none inside a tx, document why).
5. `docs/ARCHITECTURE.md` (skeleton): components, data flow diagram (mermaid), chain list, RPC requirements (archive + `debug_traceCall`).

**Gate (`make phase-1`).** A docs linter: every metric in `METRICS.md` has a definition, a parameter in `analysis/config.yaml`, and a named output field in `analysis/schemas/results.schema.json`; `STORY.md` claim table has no empty cells; mermaid renders (`@mermaid-js/mermaid-cli` smoke).

**Exit criteria.** Docs merged; a reviewer (you) can explain every number that will appear in the README before any number exists.

---

### Phase 2. Hook census and base indexer

**Objective.** Enumerate every v4 hook and pool on target chains, with flags, TVL and volume. This is the denominator for everything.

**Tasks.**

1. `index/` (Ponder): index `PoolManager.Initialize(id, currency0, currency1, fee, tickSpacing, hooks, sqrtPriceX96, tick)` and `Swap(id, sender, amount0, amount1, sqrtPriceX96, liquidity, tick, fee)` on all target chains from each PoolManager deployment block. Entities: `Hook {address, chain, flagsBitmap, firstSeen, poolCount}`, `Pool {id, key, hook, fee, dynamic, firstSeen}`, `Swap {…, sender}`.
2. Decode hook permission bits from the address (`Hooks` library semantics: `BEFORE_SWAP_FLAG`, `AFTER_SWAP_FLAG`, `BEFORE_SWAP_RETURNS_DELTA_FLAG`, `AFTER_SWAP_RETURNS_DELTA_FLAG`, etc.). Store as bitmap + booleans.
3. Bytecode fetch + hash for every hook (`analysis/pipelines/a_census.py` → `data/snapshots/census/`). Detect EIP-1967 implementation slot (upgradeable), `Ownable`-style selectors, `pause` selectors. Fetch verified source from Etherscan-family APIs where available; store `verified: bool`.
4. TVL/volume: per pool, 30-day volume in USD from `Swap` amounts × a price source (Uniswap v3/v4 stable-pair TWAPs for major assets; fall back to CoinGecko snapshot for the rest; record which). Aggregate per hook.
5. Pull `Uniswap/hooklist` `hooklist.json`; join on (chain, address); store `allowlisted: bool` and their `properties`.
6. `data/results/census.json`: per chain. Hooks total, by flag combination, with returns-delta, dynamic-fee, upgradeable, verified, allowlisted; top 100 hooks by volume.

**Gate (`make phase-2`).**

- Ponder schema tests; `pnpm --filter index test` (event decoding against recorded fixtures from real txs).
- `pytest analysis/tests/test_census.py`: flag decoding matches `Hooks.sol` for 50 known addresses (take from hooklist); bitmap round-trips; no null hook addresses.
- Reconciliation check: our total hook count per chain within ±5% of an independent count via a raw `eth_getLogs` script (`analysis/pipelines/verify_census.py`); print both.
- Snapshot manifest present with sha256.

**Exit criteria.** `census.json` produced from a pinned snapshot; the "hook census" table renders in `docs/phases/PHASE-2.md`.

**Pitfalls.** Multiple PoolManager deployments per chain (check addresses in v4-core deployments); native ETH pools (`currency0 == address(0)`); hooks serving many pools (count once); Etherscan rate limits (cache aggressively).

---

### Phase 3. Settled-trade divergence, intermittency, attribution (analyses B, C, D)

**Objective.** The headline numbers: which hooks charge, how much, when, and who routed users into them.

**Tasks.**

1. **Fill re-quote engine** (`analysis/lib/requote.py` + `contracts/script/Requote.s.sol`): for a fill `(chain, txHash, logIndex)`, run a Foundry script that `vm.rollFork(txHash)`, constructs the identical `swap` via `V4Quoter` (`quoteExactInputSingle` / `quoteExactOutputSingle`, with the fill's `hookData` if the router passed any. Recover from the tx calldata when decodable; otherwise empty and flag `hookDataUnknown`), and prints `expected`. Batch via `forge script` with `--ffi`-free JSON I/O; parallelize across worker processes with separate fork RPC connections.
2. **Cheap re-quote** (`eth_call` at block `N-1`) for bulk coverage; mark `approx=true`; compare the two methods on a 2,000-fill sample and report agreement in `docs/phases/PHASE-3.md`.
3. **Pipeline B** (`b_divergence.py`): for every fill in hooked pools (full coverage for top 500 pools by volume per chain; stratified sample elsewhere), compute expected, realized, nominal fee, excess take. Per hook: fills, charged fills, charged rate, median excess when charged, p90, max, USD total excess. Output `data/results/divergence.json` + per-hook parquet.
4. **Pipeline C** (`c_intermittency.py`): hourly charged rate per hook over 30/90 days; switch count; toxic-hour share; owner-switch correlation where an `Ownable` setter tx is observed near a regime change (join with hook tx history).
5. **Pipeline D** (`d_attribution.py`): map `Swap.sender` to products using `analysis/data/routers.csv` (Universal Router per chain, 0x settler, 1inch, Paraswap, OKX, MetaMask swaps router, CoW settlement, UniswapX executors, known filler contracts; unknown → `unlabeled`). Per product: fills into divergent hooks, USD excess, share of product's v4 volume. Include a `confidence` column and a sources column for every mapping.
6. **Sensitivity**: rerun B with charged threshold ∈ {2, 5, 10, 25} bps and min-fills ∈ {10, 20, 50}; report how the divergent-hook count moves. This preempts "you picked thresholds to get a number".
7. Write `docs/phases/PHASE-3.md` with tables and the three headline sentences, each citing the result file and snapshot hash.

**Gate (`make phase-3`).**

- `pytest analysis/tests/test_requote.py`: the two re-quote methods agree within 1 bps on ≥ 95% of a fixture sample of _hookless_ pool fills (ground truth: hookless pools should show excess take ≈ 0 ± rounding). This is the calibration test: if hookless pools show excess take, the engine is wrong.
- `test_divergence.py`: known-toxic fixtures (0x's named Base hook `0x800cef53c3fd41109dffec62e5251bdd7acba5c7`, BNB hook `0x141984423d1a28242b3dd8888c5b0daa7b13c880`) come out `divergent=True` with charged rates in the same ballpark as 0x reported (document ours next to theirs; do not tune to match).
- `test_attribution.py`: every router in `routers.csv` resolves to bytecode on its chain; no duplicate labels.
- Result schema validation against `results.schema.json`.

**Exit criteria.** `divergence.json`, `intermittency.json`, `attribution.json` produced; headline numbers appear in `PHASE-3.md` with snapshot references; hookless calibration passes.

**Pitfalls.** Exact-output fills (compare on input side); native ETH deltas sign conventions; fills inside multi-hop where `hookData` was forwarded; dynamic-fee pools where the _nominal_ fee is itself the hook's choice (report both "vs nominal" and "vs static tier" views); price source gaps for long-tail tokens (report USD figures only where price confidence is high, counts everywhere).

---

### Phase 4. `hook-probe` detection kit and precision calibration (analysis F)

**Objective.** An open, reproducible detector for spoof-capable hooks, and an honest measurement of where each method fails.

**Tasks.**

1. `probe/static`: EVM disassembler (use `evmole` or `sevm`); for each hook bytecode: env opcodes present (`GASPRICE 0x3a`, `ORIGIN 0x32`, `COINBASE 0x41`, `BASEFEE 0x48`, `PREVRANDAO 0x44`, `GASLIMIT 0x45`, `GAS 0x5a`), proxy pattern, `SELFDESTRUCT`, owner-gated fee/discount setters (heuristics over selectors + storage writes), calls back to `sender` (`IMsgSender.msgSender()` selector), `tx.origin` usage in access control.
2. `probe/dynamic`: for a pool, construct a canonical swap and run `eth_call` against `V4Quoter` (or a `ProbeRouter` view contract of ours) under permutations: `gasPrice ∈ {0, baseFee+1 gwei, 100 gwei}`, `from ∈ {EOA, contract}`, `gas ∈ {default, 2×}`; plus `debug_traceCall` capturing which env opcodes execute _on the swap path_ (not just present). Output: `envSensitive`, `signals[]`, `outputs[]`.
3. `probe/repeat`: same call N times in one `eth_call` batch to detect state-independent randomness (dice-roll with `prevrandao`/blockhash returns stable within a block; with a per-call counter it changes, but counters revert in `eth_call`; document what this can and cannot see; the _settled-trade_ method (Phase 3) is the only reliable detector for dice-roll hooks).
4. `probe/report`: JSON per hook merged into `data/results/probe.json`.
5. **Pipeline F** (`f_precision.py`): confusion matrix of static/dynamic flags vs Phase 3 `divergent`. Report precision/recall per method and the union. Expect: env probes catch sniffers, miss dice-rollers; settled trades catch both but lag. This table is a README section.

**Gate (`make phase-4`).**

- `pnpm --filter probe test`: disassembler finds `GASPRICE` in a compiled fixture that uses `tx.gasprice` and not in one that doesn't; dynamic probe flags the fixture sniffer under `gasPrice=0` vs `100 gwei`; trace confirms opcode on path.
- Against real hooks: the Enso Polygon hook (from their report) or the 0x Base hook flags `envSensitive=true` if it is still deployed and env-based; if not, document which real hook you used and why.
- `f_precision.py` runs and emits the matrix; recall on Phase 3 divergent set is reported, not asserted.

**Exit criteria.** `probe.json` and `precision.json` exist; the precision table is in `PHASE-4.md`.

---

### Phase 5. `SwornRouter` and toxic fixtures (contracts, unit/fuzz/invariant)

**Objective.** The mechanism, correct at the v4 level, with adversarial fixtures that model every observed toxic pattern.

**Design (implement exactly, then test).**

```solidity
struct Hop { PoolKey key; bool zeroForOne; bytes hookData; }
struct Candidate { Hop[] hops; }             // single- or multi-hop route
struct SwornParams {
  Currency tokenIn; Currency tokenOut;
  int256 amountSpecified;                     // <0 exact-in, >0 exact-out (v4 convention)
  uint256 minOut;                             // hard floor (or maxIn for exact-out)
  uint16 hookMarginBps;                       // hooked route must beat best hookless by this
  uint64 probeGas;                            // identical gas stipend for probe and execution
  uint8 maxProbes;
  address recipient; uint256 deadline;
  bool usePermit2; bytes permit;              // Permit2 transfer or plain transferFrom
}

function swornSwap(Candidate[] calldata cands, SwornParams calldata p) external payable returns (uint256 out);
```

Inside `unlockCallback`:

1. For `i < min(cands.length, maxProbes)`: `try this.probe{gas: p.probeGas}(cands[i], p.amountSpecified)`; `probe` executes the hops via `poolManager.swap` and reverts with `abi.encode(finalDelta)`; catch decodes to `probed[i]` or marks `UNAVAILABLE` on any other revert.
2. Select: best hookless `h*`, best hooked `k*`; choose `k*` only if `probed[k*] ≥ probed[h*] × (1 + hookMarginBps/1e4)`; else `h*`. Require chosen ≥ `minOut`. If no candidate satisfies, revert `NoRoute()`.
3. Execute chosen route with the **same** gas stipend via an internal call path that is byte-for-byte the same sequence of external calls as the probe (sender, gas, calldata identical). Assert `executedDelta == probed[chosen]`, else revert `Divergence(chosen, probed, executed)`.
4. Settle: `sync(tokenIn)`, transfer in (Permit2 `permitTransferFrom` or `transferFrom`), `settle()`; native: `settle{value}`; `take(tokenOut, recipient, amount)`; sweep dust.
5. `emit Sworn(bytes32 routeId, address hook, uint256 probed, uint256 executed, uint8 candidatesTried, uint8 chosen)`.

Rules the implementation must obey (each becomes a test):

- No storage or transient-storage difference observable by a hook between probe and execution (the router holds no phase flag; anything a hook could call on the router returns the same during both).
- `probeGas` applied to both calls; document the EIP-150 63/64 consequence and pick the stipend so both calls see the same `gasleft()` at entry (test with a `GasSniffHook` fixture that records `gasleft()` and compares).
- Probe revert data must be indistinguishable from a normal revert to outside observers (irrelevant on-chain, but keep the interface clean).
- Reentrancy: hooks may call back into `PoolManager` during our unlock (that's allowed); the router must not expose any external function that mutates state during an unlock (guard with a transient lock).
- Exact-out: compare on input side; `minOut` becomes `maxIn`.
- Multi-hop: intermediate currencies stay as PoolManager deltas (no ERC-6909 mint needed); final delta is what's compared.

**Fixtures** (`contracts/test/fixtures/`):

- `HonestHook`: static behavior.
- `GaspriceSniffHook`: 0 fee when `tx.gasprice == 0`, 18% via `beforeSwapReturnDelta` otherwise.
- `OriginSniffHook`: honest for `tx.origin == 0`/allowlisted, toxic otherwise.
- `CoinbaseBasefeeSniffHook`.
- `DiceRollHook`: fee from `prevrandao ^ counter`, with `counter` in storage (reverted in probe) and a variant using only block data (identical in probe and exec).
- `OwnerSwitchHook`: `discountBps` toggled by owner.
- `GasSniffHook`: charges more when `gasleft()` at entry differs from a recorded value.
- `RouterWhitelistHook`: honest only when `sender == knownRouter`.
- `RevertGriefHook`: reverts for non-simulation env.
- `CallbackSniffHook`: calls `sender` trying to detect a probe flag.

**Gate (`make phase-5`).**

- Unit tests for each fixture: (a) off-chain-style `eth_call` (via `vm.txGasPrice(0)` etc.) shows the attractive quote; (b) `swornSwap` with `[toxic, honest]` executes on `honest` and delivers ≥ probed honest output; (c) slippage-only reference router (`NaiveRouter`, included for comparison) loses the toxic amount.
- `DiceRollHook` block-data variant: Sworn executes on it _only_ if it actually beats honest at execution; state-counter variant: assert probe == exec (counter reverted).
- `GasSniffHook`: probe and execution observe equal `gasleft()`; document the stipend math.
- `CallbackSniffHook`: no router view differs between probe and execution (test by having the hook record what it saw).
- Fuzz: random `amountSpecified`, direction, candidate orderings; invariant: `executedDelta == probed[chosen]` always; `out ≥ minOut` or revert; router holds zero balance after every call.
- Gas report: probe overhead vs a plain v4 swap for 1, 2, 3 candidates; table into `PHASE-5.md`.
- `forge coverage` ≥ 90% lines on `SwornRouter`.

**Exit criteria.** All tests green; gas table produced; `THREAT_MODEL.md` updated with a row per fixture and the test that covers it.

---

### Phase 6. Fork tests on real toxic hooks, gas benchmarks, Sworn replay (analysis E)

**Objective.** Prove the mechanism against real deployed hooks and produce the product's ROI number.

**Tasks.**

1. Fork tests (`contracts/test/fork/`): on Base at a pinned block, the 0x-named hook pool vs the best hookless pool for the same pair. Run `swornSwap([toxicPool, honestPool])`; assert execution on the honest pool and output within 1 bps of the honest probe. Repeat on BNB. If a named hook is dormant at the pinned block, choose the most recent block where Phase 3 shows it charging; document.
2. `NaiveRouter` comparison on the same forks: show the loss.
3. **Pipeline E** (`e_replay.py`): for every charged fill in Phase 3 (top pools), simulate Sworn: find hookless candidates for the pair at that block (from census), re-quote them at the fill's state (Foundry `rollFork(txHash)`), compute protected value net of probe gas priced in output token; aggregate per chain/product/hook. Output `data/results/replay.json`: total protected USD, fills protected, median protection bps, gas overhead distribution.
4. Gas benchmarks per chain (`docs/GAS.md`): probe cost at current base fees in USD for 1–3 candidates; show it is negligible on L2s and quantify on L1.

**Gate (`make phase-6`).** Fork tests pass on Base and BNB (CI `fork.yml`); `replay.json` validates; `e_replay` unit test on 20 hand-checked fills reproduces protected values within rounding; gas table generated from `forge snapshot`.

**Exit criteria.** README-ready sentences: "On N fills through toxic hooks in [window], Sworn would have returned $X to users at a median gas overhead of Y." with sources.

---

### Phase 7. `HookBook` attestations and the attestor

**Objective.** Make honesty legible on-chain and keep it fresh.

**Tasks.**

1. `HookBook.sol`: `setScore(address hook, uint8 score, uint32 flags, uint64 asOfBlock, bytes sig)` by an authorized attestor set (start with one key, structure for N-of-M later); `score(hook)`; `flags(hook)`; events; per-chain deployment. Flags bitmap mirrors `METRICS.md`. Include `ScoreProof` struct with snapshot hash so anyone can verify the dataset behind a score.
2. `attestor/`: scheduled job (GitHub Actions cron, hourly) that runs Phases 2–4 incrementally (delta since last run), recomputes scores by the documented formula, writes `HookBook` on each chain, and commits `data/results/latest/*.json` + a signed manifest to a `data` branch.
3. `SwornRouter` optional pre-filter: `maxScore` param; skip probing hooks above it (saves gas; default off).
4. Score model calibration doc (`docs/SCORING.md`): weights, examples, how intermittency decays, minimum sample sizes, and a section "how to get your hook to 0" for honest builders.

**Gate (`make phase-7`).** `HookBook` tests (auth, replay protection on signatures, event emission); attestor dry-run against Base writes to a local anvil `HookBook` and the written scores equal the computed JSON; cron workflow validated; end-to-end: run attestor → `HookBook.score(toxicHook)` ≥ threshold, `score(honestHook)` low.

**Exit criteria.** `HookBook` deployed on at least one testnet and one L2 mainnet (Base) with real scores; explorer-verified; attestor running on schedule.

---

### Phase 8. `sworn-sdk` and integrations

**Objective.** Make Sworn adoptable in one line by wallets, aggregators and agents.

**Tasks.**

1. `sdk/` (TS, viem): `buildSwornCall({ chainId, tokenIn, tokenOut, amount, exactOut, candidates?, quote?, hookMarginBps, minOut, recipient, permit2 })` → `{ to, data, value }`. If `candidates` omitted, derive from the index (best hooked pools + best hookless pools for the pair).
2. Quote adapters: Uniswap Trading API route → candidates (parse route pools; note `hooksOptions`); generic `PoolKey[]` input for other aggregators.
3. viem action `swornSwap` and an ethers adapter; a UniswapX `IReactorCallback` executor that fills orders through `SwornRouter` (fillers get the guarantee too).
4. `HookBook` reader: `getScore(hook)` with caching; `explain(hook)` returns the flags in words.
5. Agent quickstart: a 40-line script that swaps through Sworn from an agent wallet and refuses hooks above a score.

**Gate (`make phase-8`).** SDK unit tests (calldata golden files against Foundry-generated expectations); e2e against anvil fork: SDK-built call executes and emits `Sworn`; typedoc builds; example scripts run.

**Exit criteria.** `pnpm add sworn-sdk` from a tarball works in a fresh project; docs in `sdk/README.md`.

---

### Phase 9. Dashboard and demo

**Objective.** Make the data and the guarantee visible.

**Tasks.**

1. `app/` (Next.js): pages. Hook Explorer (search, score, flags, charged rate, sparkline of hourly rate, pools, front-ends that routed into it), Chain Overview (census + divergence headline), Front-end Attribution table, Protected Value counter (from `Sworn` events), Hook Certification page ("submit your hook, see your score and how to improve it").
2. Read from the `data` branch JSON and the index; no server-side secrets needed for read paths.
3. Demo script (`docs/DEMO.md`): a 3-minute sequence on an anvil Base fork: (a) show two pools, toxic quotes better; (b) naive router: user loses 18%; (c) Sworn: probe outputs printed, routes to honest, `Divergence` assertion; (d) `HookBook.score` for both; (e) dashboard hook page. Record a screen-capture; storyboard in the doc.

**Gate (`make phase-9`).** `pnpm --filter app build` and Playwright smoke (explorer loads, a known hook page renders score and flags from results JSON); demo script runs end to end via `scripts/demo.sh` on anvil without manual steps.

**Exit criteria.** Deployed preview URL in `PHASES.md`; demo recording linked.

---

### Phase 10. README (Solvent structure), FEEDBACK.md, hooklist PR, submission

**Objective.** Tell the story with only numbers this repo produced.

**README sections (fixed order).**

1. One-paragraph thesis (the five claims compressed).
2. **The property the protocol assumes.** Quote == execution; hooks are arbitrary; routers price with `eth_call`; the API defaults to hooks-inclusive; allowlists are the only defense.
3. **Measured on mainnet.** Census; divergent hooks by chain; charged rate and median excess distributions; intermittency; front-end attribution. Each figure links to `data/results/*.json` and the snapshot hash.
4. **How spoofing works.** The env-sniff, dice-roll, owner-switch, router-whitelist patterns, each with a fixture in this repo and, where safe, a real example.
5. **Cost to exploit.** Zero: it's calldata and a modifier. Contrast with what it cost users (Phase 3 USD totals).
6. **Sworn.** The in-transaction probe; why hooks can't distinguish it; the `Divergence` assertion; route selection; gas.
7. **Sworn replay.** Protected value, fills, overhead (Phase 6).
8. **HookBook and the attestor.** Scores, flags, freshness; how honest builders certify.
9. **Detection precision.** Static vs dynamic vs settled-trade (Phase 4 matrix).
10. **What Uniswap should change.** Routers that serve agents verify in-tx; hooklist carries `divergenceScore`/`envSensitive`/`intermittent`; the "Access msg.sender" guide should point to in-tx verification for execution integrity; Trading API should expose per-route hook scores.
11. **Threat model and limits.**
12. **Reproduce everything.** Commands per phase; snapshot hashes.
13. Pointers to contract lines (prize requirement), `FEEDBACK.md`, and the hooklist PR.

**Other tasks.** `FEEDBACK.md` (time to first success, friction, missing capability, the one improvement with the greatest impact. Written from `docs/phases/*` notes kept during the build); submit the Uniswap developer feedback form with the `FEEDBACK.md` link; open the hooklist schema PR with the new fields and a generator that fills them from `HookBook`; record integration debrief.

**Gate (`make phase-10`).** README linter: every number matches a value in `data/results` (script `scripts/verify-readme-numbers.py` parses `{{result:path}}` placeholders and renders them; raw digits outside placeholders fail the check); all links resolve; `FEEDBACK.md` exists with the four required sections; submission checklist in `PHASES.md` complete.

**Exit criteria.** Tag `v0.1.0-hackathon`.

---

### Phase 11. Product hardening (post-hackathon, ambitious)

**Objective.** Turn the repo into the execution-integrity layer for anyone who routes trades.

**Tracks.**

1. **Multi-venue.** Generalize probe-and-select to non-v4 venues (Enso's second case was a Curve pool with a context-sensitive rate oracle). Adapter interface: `IVenueProbe { probe(route) → delta }` for v3, Curve, Balancer, Aerodrome/Velodrome, Maverick. Same divergence index across venues.
2. **Integrations.** Universal Router-compatible entrypoint (wrap; UR cannot host custom commands), UniswapX filler executor (Phase 8) hardened, wallet SDK plugins (MetaMask Snap / Rabby), aggregator adapters (0x, 1inch, Paraswap, Enso) that accept a `sworn: true` flag.
3. **Attestor decentralization.** N-of-M attestors; disputes; staking; publish datasets to IPFS/Arweave; verifiable computation for scores (start with signed manifests, evaluate zk-provable pipelines later).
4. **Monetization.** Router fee switch (bps on protected volume, default 0 for hackathon), API tier for the index, certification program for hook developers (fee to be scored on demand + badge).
5. **Security.** Audit prep: invariants document, differential fuzzing against v4-core, formal spec of the equality assertion; bug bounty.
6. **Research.** Publish the divergence dataset and a short paper; propose a hooklist/API standard (`divergenceScore`) and an ERC for "execution integrity attestations".

**Gate.** Each track has its own `docs/phases/PHASE-11-<track>.md` with acceptance criteria; release `v1.0.0` requires audit sign-off and 30 days of attestor uptime.

---

## 3. Data and analysis appendix

**A. Hook census.** Inputs: `Initialize` logs, bytecode, hooklist. Outputs: counts by flags; upgradeable/verified/allowlisted shares; top hooks by volume.

**B. Settled-trade divergence.** Inputs: `Swap` logs (hooked pools), tx calldata (hookData recovery), archive state. Method: Foundry `rollFork(txHash)` + `V4Quoter` (primary), block `N-1` `eth_call` (approx). Outputs: per-fill expected/realized/excess; per-hook charged rate, medians, USD.

**C. Intermittency.** Inputs: B at hourly resolution. Outputs: switches, toxic-hour share, owner-setter correlation.

**D. Attribution.** Inputs: `Swap.sender`, curated router map. Outputs: per-product exposure.

**E. Sworn replay.** Inputs: B charged fills, census hookless pools, archive state. Outputs: protected value, overhead.

**F. Detection precision.** Inputs: probe flags, B labels. Outputs: confusion matrices per method.

**Result files (schema in `analysis/schemas/results.schema.json`).** `census.json`, `divergence.json`, `intermittency.json`, `attribution.json`, `probe.json`, `precision.json`, `replay.json`, `gas.json`, `scores.json`. The README, dashboard and attestor consume only these.

**RPC needs.** Archive nodes with `debug_traceCall` on all target chains; expect tens of thousands of `rollFork` calls for Phase 3 full coverage. Batch by block, reuse forks, cache expected outputs keyed by `(chain, txHash, logIndex)`.

---

## 4. Definition of Done (whole project, hackathon tag)

- `PHASES.md` shows Phases 0–10 `DONE` with commit hashes.
- CI green on `main`; fork tests green with pinned blocks.
- `SwornRouter` + `HookBook` deployed on Base (and one more chain), addresses in README, verified.
- Attestor has written at least two consecutive scheduled updates.
- README numbers all resolve from `data/results` via the linter.
- Demo recording exists and `scripts/demo.sh` reproduces it.
- `FEEDBACK.md` + feedback form submitted; hooklist PR opened.
- Tag `v0.1.0-hackathon` pushed.

Build the numbers first. The mechanism proves the numbers can't hurt anyone again. The attestations make that provable to strangers. That is the whole project.
