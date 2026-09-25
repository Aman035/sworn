# PHASES

Append-only gate ledger. A row is written **only** by `scripts/mark-phase.sh`, and only
after that phase's gate script exited 0 — see `make gate-selftest`. Re-running a gate
appends a new row rather than editing an old one, so the history stays auditable.

Phase definitions live in `SWORN_PLAN.md`; per-phase notes in `docs/phases/PHASE-N.md`.

| Phase | Status | Date (UTC) | Commit | Gate | Evidence |
| ----- | ------ | ---------- | ------ | ---- | -------- |
