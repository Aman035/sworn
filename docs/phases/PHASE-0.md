# Phase 0 — Bootstrap, conventions, gating

> Status: DONE · Gate: `make phase-0`

## Objective

A repo where every later phase can be checked mechanically. Nothing here measures
anything; it exists so that Phases 1–11 cannot quietly skip a check.

## What was built

- **Monorepo layout** — matches `SWORN_PLAN.md` §1: `contracts/`, `analysis/`, `index/`,
  `probe/`, `attestor/`, `sdk/`, `app/`, `data/`, `docs/`, `scripts/`.
- **Foundry project** — `contracts/`, solc 0.8.26, via-IR, cancun, optimizer 800 runs.
  Dependencies are git submodules pinned by tag/commit (see `docs/ARCHITECTURE.md`).
- **pnpm workspace** — five TS packages, strict `tsconfig.base.json`
  (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`).
- **Python package** — `analysis/` installs as `sworn_analysis` while keeping the
  plan's file paths (`analysis/lib/…`, `analysis/pipelines/…`); ruff + mypy + pytest.
- **Gate runner** — `scripts/mark-phase.sh` runs the gate itself and appends to
  `PHASES.md` only on exit 0. There is no way to hand it a pre-computed pass.
- **CI** — `ci.yml` (forge fmt/build/test, TS typecheck/test, ruff/pytest, actionlint),
  `fork.yml` (nightly + `run-fork-tests` label, needs archive RPC secrets),
  `attestor.yml` (hourly cron, gated off behind the `ATTESTOR_ENABLED` repo variable
  until Phase 7).

## Gate output

```
==> repo layout
  ok  layout matches SWORN_PLAN.md §1
==> submodules pinned
  ok  v4 dependencies present
==> forge build
  ok  contracts compile (solc 0.8.26, via-IR)
==> forge test
  ok  solidity tests pass
==> pnpm typecheck
  ok  typescript strict typecheck passes
==> pnpm test
  ok  workspace tests pass
==> python tests
  ok  python tests and lint pass
==> ci workflows
 warn actionlint not installed; used the built-in YAML validator instead
==> gate runner self-test
  ok  mark-phase.sh refuses to mark a failing phase
```

Full log: `docs/phases/gate-logs/phase-0.log`. Ledger row: `PHASES.md`.

## Decisions and deviations from the plan

- **`universal-router` is referenced, not vendored.** The plan lists it as a read-only
  reference. It pulls a large dependency tree and nothing in this repo compiles against
  it, so it is pinned in `docs/ARCHITECTURE.md` by tag instead of added as a submodule.
  Revisit in Phase 11 if the UR-compatible entrypoint needs its interfaces.
- **`v4-periphery` is pinned by commit, not tag.** The repository publishes no release
  tags; `9969eec` is recorded in `docs/ARCHITECTURE.md`.
- **Python is 3.11+ rather than exactly 3.11.** `requires-python = ">=3.11"`; CI runs
  3.11 so the pinned floor stays honest while local dev can use a newer interpreter.
- **`uv`/`poetry` not used.** A plain `venv` + `pip install -e "analysis[dev]"` keeps the
  Makefile dependency-free; versions are pinned exactly in `analysis/pyproject.toml`.
- **`actionlint` is optional locally.** The gate uses it when present and falls back to
  `scripts/validate_workflows.py`; CI always runs the real `actionlint`.

- **`.env.example` is named `.env.sample`.** Renamed at the user's request; the Phase 0
  gate and `.gitignore` were updated together and the gate re-run.

## Friction (feeds FEEDBACK.md)

- `Uniswap/v4-periphery` has no release tags, so downstream builders cannot pin to a
  reviewed version — every integrator ends up pinning an arbitrary `main` commit.
- `Uniswap/permit2`'s only tag is the deployed address string, which is not a version.

## Next

Phase 1 freezes the metric definitions (`docs/METRICS.md`), the parameters in
`analysis/config.yaml` and the output fields in `analysis/schemas/results.schema.json`
*before* any data is pulled, so the numbers cannot drift later.
