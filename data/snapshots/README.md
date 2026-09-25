# Snapshots

One directory per pinned data pull. Raw rows are **not** committed (see `.gitignore`);
what is committed is the manifest, so anyone can re-pull the exact same range and check
the hash.

```
data/snapshots/<name>/
  MANIFEST.json   # chain, block range, RPC provider, script commit, row counts, sha256
  <name>.parquet  # gitignored
```

`MANIFEST.json` is written by `analysis/lib/snapshot.py`; nothing else may write it.
Every file in `data/results/` names the snapshot it was computed from.
