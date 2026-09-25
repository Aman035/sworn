"""Record each chain's PoolManager deployment block into analysis/data/deployments.json.

Run once, and again after adding a chain. The census reads the result; it never guesses a
start block.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from dotenv import load_dotenv  # noqa: E402

from lib.config import chains  # noqa: E402
from lib.deployments import (  # noqa: E402
    Deployment,
    code_size,
    find_deployment_block,
    load_deployments,
    pool_manager,
    save_deployments,
    verify_pool_manager,
)
from lib.rpc import RpcClient, redact, scrub  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    existing = load_deployments()
    found: dict[str, Deployment] = dict(existing)
    failures: list[str] = []

    for name, chain in sorted(chains().items(), key=lambda kv: kv[1].priority):
        url = os.environ.get(chain.rpc_env)
        if not url:
            print(f"  --  {name:<9} {chain.rpc_env} unset, skipping")
            continue

        address = pool_manager(name)
        try:
            with RpcClient(url, timeout=60) as rpc:
                ok, detail = verify_pool_manager(rpc, chain)
                if not ok:
                    failures.append(f"{name}: {detail}")
                    print(f"  FAIL {name:<9} {detail}")
                    continue

                if name in existing:
                    print(
                        f"  ok   {name:<9} block {existing[name].deployment_block:,} (cached) — {detail}"
                    )
                    continue

                block = find_deployment_block(rpc, address)
                found[name] = Deployment(name, address, block, code_size(rpc, address))
                print(f"  ok   {name:<9} deployed at block {block:,} — {detail}")
        except Exception as exc:  # noqa: BLE001 — one bad endpoint must not stop the rest
            # scrub: provider errors embed the full URL, and the URL embeds the API key.
            failures.append(f"{name}: {type(exc).__name__}: {scrub(str(exc), url)}")
            print(f"  FAIL {name:<9} {redact(url)}: {type(exc).__name__}")

    save_deployments(found)
    print(f"\nwrote {len(found)} deployment(s) to analysis/data/deployments.json")
    if failures:
        print("\nproblems:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
