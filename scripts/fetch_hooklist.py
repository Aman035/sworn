"""Fetch Uniswap's hooklist.json into a pinned snapshot with a manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from lib.hooklist import HOOKLIST_URL, cache_path, fetch, load  # noqa: E402
from lib.snapshot import write_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-download even if cached"
    )
    args = parser.parse_args()

    path = fetch(force=args.force)
    entries = load(path)
    chains = {e.chain_id for e in entries if e.chain_id is not None}

    write_manifest(
        "hooklist",
        chain="multi",
        chain_id=0,
        block_from=0,
        block_to=0,
        rpc_provider="raw.githubusercontent.com/Uniswap/hooklist",
        rows=len(entries),
        files=[cache_path()],
        source=HOOKLIST_URL,
        notes=f"{len(chains)} chains represented",
    )
    print(f"hooklist: {len(entries):,} entries across {len(chains)} chains -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
