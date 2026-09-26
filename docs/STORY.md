# Story

Five claims. Everything in this repo exists to make them true and demonstrable, and each
one is owned by an artefact that produces it, not by prose.

| Claim                                                                                                                                                                                                             | Source                                                                                                                                                                                                                                                                                                                    | Our artifact                                                                                                                                                    | Phase |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| The protocol assumes quote == execution and never enforces it: a hook is arbitrary code inside every swap, routers price with `eth_call`, and the only defences shipped are allowlists and proprietary detection. | [Uniswap `hooklist`](https://github.com/Uniswap/hooklist) (allowlist as the shipped answer); [0x, 14 Sep 2026](https://0x.org/post/uniswap-v4-hooks-were-a-mistake) (closed detection). See `SOURCES.md`                                                                                                                  | `docs/THREAT_MODEL.md` + the fixture suite in `contracts/test/fixtures/`, where each spoofing capability is a working hook and a passing test                   | 1, 5  |
| Measured on mainnet the gap is large and intermittent, and it is measurable with open tooling.                                                                                                                    | [0x, 14 Sep 2026](https://0x.org/post/uniswap-v4-hooks-were-a-mistake): 84,163 hooks, 19.4% safe / 54.2% malicious / 26.4% likely malicious, fills up to 50% below quote; [Enso, 16 Jul 2026](https://blog.enso.build/toxic-pools/): ~98.9% fee above 100 gwei, a pool toxic ~59% of 718 observed hours, toggled 26 times | `data/results/census.json`, `divergence.json`, `intermittency.json`, `attribution.json`. Our numbers, per hook, per hour, per front-end, from a pinned snapshot | 2, 3  |
| The fix is a routing primitive, not a blacklist: probe every candidate inside the real transaction, execute the best, assert executed == probed.                                                                  | [Enso, 16 Jul 2026](https://blog.enso.build/toxic-pools/): a pool toggled 26 times across 48 windows, which no allowlist refresh rate can track                                                                                                                                                                           | `contracts/src/SwornRouter.sol` + the `Divergence` assertion, proved against every fixture and against real hooks on forked Base and BNB                        | 5, 6  |
| Honesty becomes attestable, so honest hook builders stop being delisted wholesale with the rest.                                                                                                                  | [Uniswap `hooklist`](https://github.com/Uniswap/hooklist): registry entries carry no behavioural evidence, only curation                                                                                                                                                                                                  | `contracts/src/HookBook.sol` + `attestor/` writing `data/results/scores.json` on a schedule, with a snapshot hash per score                                     | 7     |
| This is a product, not a demo: wallets, aggregators and agents carry reimbursement and liability risk for every quote they show.                                                                                  | [Enso, 16 Jul 2026](https://blog.enso.build/toxic-pools/): MetaMask routed 6,625 swaps, ~$5.88M USDC volume, through a pool during its toxic periods                                                                                                                                                                      | `sdk/` (one-line adoption), `app/` (the index and the protected-value counter), `data/results/replay.json` (the ROI number)                                     | 8, 9  |

---

## How the claims chain together

Claim 2 is the denominator: without numbers, claim 3 is a solution looking for a problem.
Claim 3 is the only one that generalises: a blacklist is always one toggle behind, an
in-transaction assertion is not. Claim 4 exists because claim 3, deployed alone, would
push routers toward "no hooks at all", which kills the honest half of the ecosystem.
Claim 5 is why any of it gets maintained after the hackathon.

## The one sentence

**Routers price a swap with `eth_call` and pay for it with a transaction; Sworn makes
those two the same thing, and publishes what happens when they are not.**

## Rules this story imposes on the repo

- No number appears in `README.md` that was not written to `data/results/*.json` by a
  script here, from a snapshot with a recorded sha256.
- Where an external report and our pipeline disagree, both numbers are shown. Parameters
  are never tuned to close the gap; the sensitivity sweep in Phase 3 exists so a reader
  can see what the choice of threshold is worth.
- `divergent` is a measurement, not an accusation. See the limits section of
  `METRICS.md`.
