# `index/` — superseded by `analysis/`

The plan called for a Ponder app to index `PoolManager.Initialize` and `Swap` across every
target chain. That work exists and runs, in Python rather than TypeScript:

| Planned here | Actually built |
| ------------ | -------------- |
| `Initialize` indexing, `Pool` / `Hook` entities | [`analysis/pipelines/a_census.py`](../analysis/pipelines/a_census.py) |
| `Swap` indexing, `Fill` entities | [`analysis/pipelines/b_fills.py`](../analysis/pipelines/b_fills.py) |
| Adaptive log fetching across providers | [`analysis/lib/logs.py`](../analysis/lib/logs.py) |
| Storage and incremental compaction | [`analysis/lib/compact.py`](../analysis/lib/compact.py) |

**Why the change.** The analysis that consumes this data is pandas, and every figure in the
repo has to trace back to a hashed snapshot. Indexing into a database and then exporting to
parquet for analysis would have put a mutable store in the middle of a provenance chain
whose whole point is that it is reproducible from an immutable snapshot. Reading logs
straight to parquet keeps one artefact, one hash, one language.

It also had to survive conditions a Ponder app would not have: Base's 30-day window is
12,855,496 fills and 8.5 GB of raw responses against 11 GB of free disk, which is why
`compact.py` slices, compacts and prunes as it goes.

This package is kept as a workspace member so the layout still matches `SWORN_PLAN.md`.
Nothing imports it.
