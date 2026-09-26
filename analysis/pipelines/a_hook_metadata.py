"""Pipeline A2. Per-hook metadata: bytecode, proxy pattern, verification.

The census says which hooks exist. This says what they *are*: how big the code is, what
it hashes to, whether it is a proxy (and therefore whether today's bytecode is any guide
to tomorrow's), which environment opcodes it even contains, and whether its source is
verified.

Two sources, with very different costs:

* **RPC**. `eth_getCode` plus the EIP-1967 storage slots. Parallel, cheap, and covers
  every hook. This is where `upgradeable` really comes from.
* **Etherscan**. `verified`, the contract name, and Etherscan's own proxy verdict. Rate
  limited to a few calls a second, so it runs over the highest-impact hooks by default
  and is cached on disk forever after.

    python -m sworn_analysis.pipelines.a_hook_metadata --chain base
    python -m sworn_analysis.pipelines.a_hook_metadata --chain base --etherscan-top 2000
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from ..lib.compact import load_shards
from ..lib.config import Chain, chains, repo_root
from ..lib.etherscan import EtherscanClient, EtherscanError
from ..lib.evm import (
    EIP1822_PROXIABLE,
    EIP1967_BEACON,
    EIP1967_IMPLEMENTATION,
    analyse,
)
from ..lib.rpc import RpcClient, RpcError, redact
from ..lib.snapshot import snapshot_dir, write_manifest

DEFAULT_WORKERS = 8
DEFAULT_ETHERSCAN_TOP = 500

ZERO_WORD = "0x" + "0" * 64


@dataclass
class HookMetadata:
    chain: str
    address: str
    pool_count: int
    code_size: int = 0
    code_sha256: str = ""
    env_opcodes: str = ""
    notable_opcodes: str = ""
    selector_count: int = 0
    minimal_proxy: bool = False
    has_delegatecall: bool = False
    has_selfdestruct: bool = False
    eip1967_implementation: str = ""
    eip1967_beacon: str = ""
    eip1822_proxiable: str = ""
    upgradeable: bool = False
    verified: bool = False
    contract_name: str = ""
    etherscan_proxy: bool = False
    error: str = ""


def _slot(rpc: RpcClient, address: str, slot: str) -> str:
    """Read a storage slot and return the address it holds, or "" when empty."""
    value = rpc.call("eth_getStorageAt", [address, slot, "latest"])
    if not value or value == ZERO_WORD:
        return ""
    tail = value[-40:]
    return "" if int(tail, 16) == 0 else "0x" + tail.lower()


def fetch_one(url: str, chain_name: str, address: str, pool_count: int) -> HookMetadata:
    meta = HookMetadata(chain=chain_name, address=address, pool_count=pool_count)
    try:
        with RpcClient(url, timeout=45) as rpc:
            code_hex = rpc.call("eth_getCode", [address, "latest"])
            code = bytes.fromhex(code_hex[2:] if code_hex.startswith("0x") else code_hex)
            report = analyse(address, code)

            meta.code_size = report.size
            meta.code_sha256 = report.sha256
            meta.env_opcodes = "|".join(report.env_opcodes)
            meta.notable_opcodes = "|".join(report.notable)
            meta.selector_count = len(report.selectors)
            meta.minimal_proxy = report.minimal_proxy
            meta.has_delegatecall = report.has_delegatecall
            meta.has_selfdestruct = report.has_selfdestruct

            meta.eip1967_implementation = _slot(rpc, address, EIP1967_IMPLEMENTATION)
            meta.eip1967_beacon = _slot(rpc, address, EIP1967_BEACON)
            meta.eip1822_proxiable = _slot(rpc, address, EIP1822_PROXIABLE)

            # A hook is upgradeable if it delegates to code it can point elsewhere. A
            # minimal proxy is *not* upgradeable: its target is baked into the bytecode.
            meta.upgradeable = bool(
                meta.eip1967_implementation or meta.eip1967_beacon or meta.eip1822_proxiable
            )
    except (RpcError, ValueError) as exc:
        meta.error = f"{type(exc).__name__}: {exc}"[:160]
    except Exception as exc:  # noqa: BLE001, one hook must not abort the sweep
        meta.error = f"{type(exc).__name__}"[:160]
    return meta


def collect(
    chain: Chain,
    *,
    workers: int = DEFAULT_WORKERS,
    limit: int | None = None,
    etherscan_top: int = DEFAULT_ETHERSCAN_TOP,
) -> pd.DataFrame:
    url = os.environ.get(chain.rpc_env)
    if not url:
        raise RuntimeError(f"{chain.rpc_env} is not set")

    directory = snapshot_dir(f"census-{chain.name}")
    census = load_shards(directory)
    if census.empty:
        raise RuntimeError(f"no census shards for {chain.name}")

    hooked = census[~census["hookless"]]
    counts = hooked.groupby("hook").size().sort_values(ascending=False)
    if limit:
        counts = counts.head(limit)

    print(f"{chain.name}: {len(counts):,} distinct hooks via {redact(url)}", flush=True)

    results: list[HookMetadata] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_one, url, chain.name, address, int(n)): address
            for address, n in counts.items()
        }
        for i, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if i % 500 == 0 or i == len(futures):
                rate = i / max(1e-9, time.time() - started)
                print(
                    f"  {chain.name}: {i:,}/{len(futures):,} hooks "
                    f"({rate:.0f}/s, {(len(futures) - i) / max(rate, 1e-9) / 60:.1f}m left)",
                    flush=True,
                )

    frame = pd.DataFrame([asdict(m) for m in results])

    if etherscan_top > 0:
        frame = _add_etherscan(frame, chain, etherscan_top)

    return frame.sort_values("pool_count", ascending=False).reset_index(drop=True)


def _add_etherscan(frame: pd.DataFrame, chain: Chain, top: int) -> pd.DataFrame:
    """Fill verification metadata for the highest-impact hooks.

    Deliberately not every hook: at a few calls a second, a full sweep of Base's hooks is
    hours. The ones that matter for the story are the ones carrying pools.
    """
    key = os.environ.get("ETHERSCAN_KEY", "")
    if not key:
        print("  ETHERSCAN_KEY unset; skipping verification metadata", file=sys.stderr)
        return frame

    targets = frame.nlargest(min(top, len(frame)), "pool_count")["address"].tolist()
    print(f"  {chain.name}: etherscan lookup for top {len(targets):,} hooks", flush=True)

    verified: dict[str, dict[str, Any]] = {}
    try:
        with EtherscanClient(key) as es:
            for i, address in enumerate(targets, start=1):
                try:
                    info = es.source(chain.chain_id, address)
                except (EtherscanError, Exception):  # noqa: BLE001. Skip and continue
                    continue
                verified[address] = {
                    "verified": info.verified,
                    "contract_name": info.name,
                    "etherscan_proxy": info.upgradeable_by_proxy,
                }
                if i % 200 == 0:
                    print(
                        f"    {i:,}/{len(targets):,} (api {es.api_calls}, cache {es.cache_hits})",
                        flush=True,
                    )
    except EtherscanError as exc:
        print(f"  etherscan unavailable: {exc}", file=sys.stderr)
        return frame

    for column in ("verified", "contract_name", "etherscan_proxy"):
        frame[column] = frame.apply(
            lambda r, c=column: verified.get(r["address"], {}).get(c, r[c]), axis=1
        )

    # Etherscan sees proxies our slot probe cannot (its detection is not slot-based), so
    # either signal is enough to call a hook upgradeable.
    frame["upgradeable"] = frame["upgradeable"] | frame["etherscan_proxy"]
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", action="append")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--limit", type=int, default=None, help="only the top N hooks by pools")
    parser.add_argument("--etherscan-top", type=int, default=DEFAULT_ETHERSCAN_TOP)
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    known = chains()
    selected = list(known) if args.all else (args.chain or ["base"])

    failures: list[str] = []
    for name in selected:
        if name not in known:
            failures.append(f"unknown chain {name}")
            continue
        try:
            frame = collect(
                known[name],
                workers=args.workers,
                limit=args.limit,
                etherscan_top=args.etherscan_top,
            )
        except Exception as exc:  # noqa: BLE001. Continue to the next chain
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  FAIL {name}: {exc}", file=sys.stderr)
            continue

        directory = snapshot_dir(f"hooks-{name}")
        directory.mkdir(parents=True, exist_ok=True)
        out = directory / "hooks.parquet"
        frame.to_parquet(out, index=False)

        errors = int((frame["error"] != "").sum())
        write_manifest(
            f"hooks-{name}",
            chain=name,
            chain_id=known[name].chain_id,
            block_from=0,
            block_to=0,
            rpc_provider=redact(os.environ.get(known[name].rpc_env, "")),
            rows=len(frame),
            files=[out],
            source="eth_getCode + EIP-1967 slots + etherscan getsourcecode",
            notes=f"{errors} hooks failed to fetch" if errors else "",
        )

        print(
            f"  {name}: {len(frame):,} hooks  "
            f"upgradeable {int(frame['upgradeable'].sum()):,}  "
            f"verified {int(frame['verified'].sum()):,}  "
            f"env-opcode-bearing {int((frame['env_opcodes'] != '').sum()):,}  "
            f"errors {errors:,}"
        )

    if failures:
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
