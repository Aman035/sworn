# Sources

The external work that motivates this repo. Two rules:

1. **We reproduce, we do not reuse.** Every number Sworn publishes is computed by a
   script in this repo from a pinned snapshot. Figures below are context and a sanity
   check on our own pipeline — never a substitute for it. Where our number differs from
   theirs, both are printed side by side and the difference is explained, not tuned away.
2. **Every figure here is quoted, dated and attributed.** A figure whose source we have
   not opened is marked `unverified` and may not be cited in the README.

---

### 0x — "Uniswap v4 hooks were a mistake"

- **URL.** <https://0x.org/post/uniswap-v4-hooks-were-a-mistake>
- **Date.** 14 September 2026
- **Status.** Verified (page fetched 25 September 2026).
- **Method they used.** Static analysis, dynamic analysis and settled-trade observation
  across six chains. Tooling is not open.

**Figures we cite.**

| Figure                   | Value                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------ |
| Hooks analysed           | 84,163 across 6 chains                                                                                 |
| Safe                     | 19.4%                                                                                                  |
| Malicious                | 54.2%                                                                                                  |
| Likely malicious         | 26.4%                                                                                                  |
| Worst observed shortfall | "as much as 50% less at execution than the amount quoted"                                              |
| Named hook (Base)        | `0x800cef53c3fd41109dffec62e5251bdd7acba5c7`, ETH/NVDAc, median fee when charged 18%, $143,037 charged |
| Named hook (BNB)         | `0x141984423d1a28242b3dd8888c5b0daa7b13c880`, USDT/WBNB, fee range 0–12.8%, $18,592 charged            |

**What we reproduce.** The census (Phase 2) and the malicious share (Phase 3), with our
own thresholds published and swept. The two named hooks are the fixtures our Phase 3
tests and Phase 6 fork tests must reproduce behaviour for — we report our charged rate
next to theirs and do **not** tune parameters to match.

**Response worth recording.** Hayden Adams publicly disputed the framing, arguing this
is inherent to permissionless systems rather than a v4 design flaw. Sworn takes no
position on that: the point of this repo is that the gap is _measurable_ and, separately,
_closable at execution time_, which is true either way.

---

### Enso — "Toxic Pools: How Manipulated Quotes Create Execution, UX, and Liability Risk in DeFi"

- **URL.** <https://blog.enso.build/toxic-pools/>
- **Date.** 16 July 2026
- **Status.** Verified (page fetched 25 September 2026).
- **Method they used.** Production observation of two pools. Tooling is not open.

**Figures we cite.**

| Figure                        | Value                                                                                              |
| ----------------------------- | -------------------------------------------------------------------------------------------------- |
| Polygon v4 hook (USDC/WETH)   | "~98.9% fee whenever gas price exceeded 100 gwei"                                                  |
| Polygon hook failed swaps     | 37,467; ~93% of reverted attempts from MEV/arbitrage bots                                          |
| Curve pool (Ethereum)         | `0xe60B5E323D72a914b089f137eC9b3aB91ae24A65` (USDC/USDT)                                           |
| Toxic share of observed hours | "roughly 423 of 718 hours, or about 59% of the time"                                               |
| Switch toggles                | "toggled 26 times across 48 observed windows"                                                      |
| Overquotes                    | "approximately $225,000"                                                                           |
| Reverted transactions         | 37,425                                                                                             |
| Succeeded but underfilled     | 129,070                                                                                            |
| MetaMask exposure             | 6,625 swaps routed; 4,420 single-hop USDT→USDC completed; ~$5.88M USDC volume during toxic periods |

**What we reproduce.** Intermittency (Phase 3, pipeline C) — the toggling regime is the
part allowlists structurally cannot catch — and front-end attribution (pipeline D), which
is what turns "a bad pool exists" into "this product routed users into it".

**Note on scope.** The Curve case is not a v4 hook. It is the reason Phase 11 generalises
probe-and-select to non-v4 venues: the vulnerability is quote-vs-execution, not hooks.

---

### Uniswap — `hooklist` registry

- **URL.** <https://github.com/Uniswap/hooklist>
- **Date.** Continuously updated; accessed 25 September 2026, and re-read at Phase 2 snapshot time (the exact commit goes in the snapshot manifest).
- **Status.** Verified (repository exists; `hooklist.json`, per-chain files under
  `hooks/`, and `schema.json` define the format).

**Figures we cite.** None — this is a _join key_, not a measurement. Phase 2 joins it on
`(chain, address)` to mark `allowlisted`, and Phase 10 opens a schema PR proposing
`divergenceScore`, `envSensitive` and `intermittent` fields generated from `HookBook`.

**Why it matters to the argument.** The hooklist is the current answer to hook risk: a
curated allowlist. An allowlist is refreshed on human timescales; the Enso Curve pool
toggled 26 times across 48 windows. That gap is the argument for per-transaction
verification rather than per-hook reputation.

---

### Uniswap — "Access `msg.sender` inside a hook" guide

- **URL.** <https://docs.uniswap.org/contracts/v4/guides/hooks/msg-sender>
- **Date.** Undated docs page; recorded 25 September 2026.
- **Status.** `unverified` — recorded from `SWORN_PLAN.md`; the URL has not been fetched
  in-repo, so it may not be cited in the README until Phase 10 re-checks it.

**Figures we cite.** None.

**Why it matters.** The guide shows a hook how to learn who the real swapper is. The same
mechanism is what lets a hook whitelist a router or an address — including, in principle,
`SwornRouter` itself. Phase 5's `RouterWhitelistHook` fixture models exactly this, and
Phase 10 proposes the guide point at in-transaction verification for execution integrity.

---

### Uniswap — Trading API `hooksOptions`

- **URL.** <https://docs.uniswap.org/api/trading/overview>
- **Date.** Undated docs page; recorded 25 September 2026.
- **Status.** `unverified` — recorded from `SWORN_PLAN.md`; not fetched in-repo.

**Figures we cite.** None.

**Why it matters.** The routing API exposes an option for how hooked pools are treated,
and the default is hooks-inclusive. That default is where the exposure in pipeline D
comes from, and it is the concrete thing Phase 10 asks to change: expose a per-route hook
score so an integrator can make the decision deliberately.

---

## Verification policy

`unverified` entries are allowed to exist here and are not allowed in `README.md`. The
Phase 10 README linter resolves every link; the Phase 1 docs linter requires each entry
above to carry a URL, a date and a **Figures we cite.** line.
