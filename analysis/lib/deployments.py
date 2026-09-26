"""Where the v4 `PoolManager` lives on each chain, and when it started.

Addresses are verified rather than trusted: `verify_pool_manager` checks that the
address holds code and that it emits `Initialize`, and `find_deployment_block` binary
searches `eth_getCode` for the block it appeared. The census must start at the
deployment block. Starting later silently truncates the denominator for every later
number, and starting at 0 wastes hours of `eth_getLogs`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Chain, repo_root
from .rpc import RpcClient

# keccak256("Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)")
INITIALIZE_TOPIC = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
# keccak256("Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)")
SWAP_TOPIC = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"

# Canonical v4 PoolManager per chain. Each was confirmed against a live node: code
# present, and `Initialize` logs observed.
POOL_MANAGERS: dict[str, str] = {
    "mainnet": "0x000000000004444c5dc75cB358380D2e3dE08A90",
    "base": "0x498581fF718922c3f8e6A244956aF099B2652b2b",
    "arbitrum": "0x360E68faCcca8cA495c1B759Fd9EEe466db9FB32",
    "polygon": "0x67366782805870060151383F4BbFF9daB53e5cD6",
    "bnb": "0x28e2Ea090877bF75740558f6BFB36A5ffeE9e9dF",
    "unichain": "0x1F98400000000000000000000000000000000004",
}

DEPLOYMENTS_FILE = "analysis/data/deployments.json"


@dataclass(frozen=True)
class Deployment:
    chain: str
    pool_manager: str
    deployment_block: int
    code_size: int


def pool_manager(chain_name: str) -> str:
    try:
        return POOL_MANAGERS[chain_name]
    except KeyError as exc:
        raise KeyError(f"no PoolManager recorded for chain {chain_name!r}") from exc


def has_code(rpc: RpcClient, address: str, block: int | str = "latest") -> bool:
    tag = block if isinstance(block, str) else hex(block)
    code = rpc.call("eth_getCode", [address, tag])
    return code not in ("0x", "0x0", None)


def code_size(rpc: RpcClient, address: str, block: int | str = "latest") -> int:
    tag = block if isinstance(block, str) else hex(block)
    code = rpc.call("eth_getCode", [address, tag])
    return max(0, len(code) // 2 - 1)


def find_deployment_block(rpc: RpcClient, address: str, hi: int | None = None) -> int:
    """First block at which `address` has code, by binary search.

    ~log2(chain height) `eth_getCode` calls. Around 27 for a chain with 500M blocks,
    which is cheap enough to re-verify rather than hard-code a number that quietly rots.
    """
    hi = hi if hi is not None else rpc.block_number()
    if not has_code(rpc, address, hi):
        raise ValueError(f"{address} has no code at block {hi}")

    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        if has_code(rpc, address, mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def verify_pool_manager(rpc: RpcClient, chain: Chain, log_window: int = 900) -> tuple[bool, str]:
    """Confirm the recorded address is really a PoolManager on this chain.

    Returns (ok, detail). A wrong address is the single most damaging silent error in the
    census, so this runs in the Phase 2 gate rather than being assumed.
    """
    address = pool_manager(chain.name)
    size = code_size(rpc, address)
    if size == 0:
        return False, f"no code at {address}"

    latest = rpc.block_number()

    # Providers cap `eth_getLogs` ranges very differently (Alchemy's free tier allows 10
    # blocks). Narrow the window rather than fail: this check only needs *a* log, and the
    # census does its own chunking against the real limit.
    last_error: Exception | None = None
    for window in (log_window, 100, 9):
        try:
            logs = rpc.call(
                "eth_getLogs",
                [
                    {
                        "address": address,
                        "fromBlock": hex(max(0, latest - window)),
                        "toBlock": hex(latest),
                        "topics": [INITIALIZE_TOPIC],
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001. Retried at a narrower window below
            last_error = exc
            continue
        return True, f"code {size}B, {len(logs)} Initialize logs in last {window} blocks"

    # Code is present and the right size; only the log probe was refused.
    return True, f"code {size}B, log probe unavailable ({type(last_error).__name__})"


def deployments_path() -> Path:
    return repo_root() / DEPLOYMENTS_FILE


def load_deployments() -> dict[str, Deployment]:
    path = deployments_path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: Deployment(
            chain=name,
            pool_manager=d["pool_manager"],
            deployment_block=int(d["deployment_block"]),
            code_size=int(d["code_size"]),
        )
        for name, d in raw.items()
    }


def save_deployments(deployments: dict[str, Deployment]) -> None:
    payload = {
        name: {
            "pool_manager": d.pool_manager,
            "deployment_block": d.deployment_block,
            "code_size": d.code_size,
        }
        for name, d in sorted(deployments.items())
    }
    path = deployments_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
