# PHASES

Append-only gate ledger. A row is written **only** by `scripts/mark-phase.sh`, and only
after that phase's gate script exited 0 — see `make gate-selftest`. Re-running a gate
appends a new row rather than editing an old one, so the history stays auditable.

Phase definitions live in `SWORN_PLAN.md`; per-phase notes in `docs/phases/PHASE-N.md`.

| Phase | Status  | Date (UTC)           | Commit          | Gate                          | Evidence                                                                                                                                                                      |
| ----- | ------- | -------------------- | --------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0     | DONE    | 2026-09-25T10:45:36Z | `525b955`       | `make phase-0` — 8 checks ok  | [gate log](docs/phases/gate-logs/phase-0.log), [notes](docs/phases/PHASE-0.md)                                                                                                |
| 1     | DONE    | 2026-09-25T13:08:01Z | `49b30c0-dirty` | `make phase-1` — 11 checks ok | [gate log](docs/phases/gate-logs/phase-1.log), [notes](docs/phases/PHASE-1.md)                                                                                                |
| 0     | DONE    | 2026-09-25T13:13:54Z | `19645dc-dirty` | `make phase-0` — 8 checks ok  | [gate log](docs/phases/gate-logs/phase-0.log), [notes](docs/phases/PHASE-0.md)                                                                                                |
| 3     | BLOCKED | 2026-09-25T16:06:58Z | `d0f2f28-dirty` | not run                       | hookless calibration at 40% (needs 95%): 6/10 fills cannot be reconciled with pre-transaction state; quoter verified correct for the state given — see docs/phases/PHASE-3.md |
| 2     | DONE    | 2026-09-25T21:11:25Z | `5539423-dirty` | `make phase-2` — 7 checks ok  | [gate log](docs/phases/gate-logs/phase-2.log), [notes](docs/phases/PHASE-2.md)                                                                                                |
| 5     | DONE    | 2026-09-25T21:23:53Z | `4e932f0-dirty` | `make phase-5` — 6 checks ok  | [gate log](docs/phases/gate-logs/phase-5.log), [notes](docs/phases/PHASE-5.md)                                                                                                |
