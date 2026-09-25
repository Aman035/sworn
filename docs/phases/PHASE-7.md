# Phase 7 — `HookBook` attestations and the attestor

> Status: DONE · Gate: `make phase-7`

## Objective

Make honesty legible on-chain, and keep it fresh.

## Deployed

**`0x8A4470f7DDa8525b484527b21B19c3bc876A04c3`** on Base Sepolia (chain 84532), source
verified on the explorer. Deploy cost 0.000008 ETH; one authorised attestor.

## The three properties that matter

**Absence is not innocence.** An unscored hook returns `hasScore() == false` and
`flags() == INSUFFICIENT_DATA`, never a clean 0. Verified against the live contract: the
0x-named Base hook, which nobody has scored, reads `flags = 1024`.

This is the load-bearing decision in the whole design and it cuts both ways. A hook cannot
earn a clean rating by not trading — otherwise the cheapest route to a perfect score would
be to deploy, wait, and turn toxic later. And an honest builder's 0 means something
precisely because it can only be reached by being measured.

The property is preserved end to end: `HookBook` distinguishes the two cases on-chain, the
attestor **skips** unscored hooks rather than writing zeros, the SDK's `explain()` renders
"never measured — absence of a score is not evidence of honesty", and `isAcceptable()`
rejects them when a ceiling is requested.

**Updates are monotonic in `asOfBlock`.** That is replay protection and staleness
protection in one: a re-broadcast signature is rejected for the same reason a late arrival
is — it describes a world that has been superseded.

**Scores are advisory and the execution path never reads them.** A stale, wrong or absent
score cannot cause a bad fill. At worst it costs gas by skipping a probe.

## Scoring

`analysis/lib/scoring.py` reproduces the worked example in `METRICS.md` **exactly** —
score 67, decay 0.8620, and all seven contributions to four decimals. That test found a
rounding error in the documentation rather than in the code: 0.5^(3/14) is 0.8620, not the
0.8623 originally written.

Behaviour carries 0.55 of the weight (charged rate and median excess); capabilities carry
0.10 (upgradeable, owner switches). A proxy hook that has never charged anyone scores 5,
not 50. Context flags — `ALLOWLISTED`, `VERIFIED`, `DYNAMIC_FEE`, `RETURNS_DELTA` — are
recorded but carry **no weight**, so a hook cannot buy a better number by getting listed,
and cannot be punished for holding a permission it uses honestly. Asserted by
`test_context_flags_carry_no_weight`.

## Current output

`data/results/scores.json`: **69,242 Base hooks, 0 scored, 69,242 `INSUFFICIENT_DATA`.**

That is the correct answer, not a degraded one. Phase 3's behavioural evidence is not yet
computed for these hooks, and a hook that has not been measured has not been cleared. The
attestor's dry-run publishes nothing and says so.

## Gate output

```
  ok  auth, freshness, signatures and replay protection
  ok  bit positions frozen and consistent
  ok  score, decay and every contribution match METRICS.md
      69,242 hooks: 0 scored, 69,242 insufficient data
  ok  every score carries the snapshot it can be re-derived from
  ok  skips unscored hooks rather than writing them as zero
  ok  attestor runs end to end
      0x8A44…04c3: 5140 bytes, 1 attestor(s), unscored reads INSUFFICIENT_DATA
  ok  deployed, authorised, and absence reads as absence
```

## Decisions and deviations from the plan

- **Flag bits are frozen and cross-checked.** `HookBook` stores the word verbatim, so a
  renumbering would silently reinterpret every score already written. A Python test parses
  the Solidity constants and compares them with `analysis/config.yaml`.
- **EIP-712 signatures, relayable by anyone.** The plan's `setScore(..., bytes sig)` is
  implemented so the attestor key can stay off any hot path and hold no gas. Malleable
  signatures are rejected.
- **Base mainnet deployment is deferred.** The plan's exit criteria include one L2
  mainnet. Deploying a registry that can only publish `INSUFFICIENT_DATA` would put an
  empty contract at a permanent address; it waits for Phase 3's scores.

## Friction (feeds FEEDBACK.md)

- Etherscan's free tier enforces 3 calls/second as a *burst* limit and reports throttling
  as HTTP 200 with `status: "0"`, so it has to be read from the body. A metadata sweep
  died on it mid-run.
