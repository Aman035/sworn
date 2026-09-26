"""Uniswap's `hooklist` registry: the allowlist Sworn measures itself against.

The hooklist is the answer the ecosystem ships today. Curation. It records what a hook
*is* (name, deployer, verified source, upgradeable) but nothing about how it *behaves*.
Joining it to the census gives the `allowlisted` column, and its per-hook permission
booleans double as an independent check on decoding permissions from the address bits.

Source: https://github.com/Uniswap/hooklist (`hooklist.json` on `main`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import repo_root
from .hookflags import FLAGS, normalize

HOOKLIST_URL = "https://raw.githubusercontent.com/Uniswap/hooklist/main/hooklist.json"
CACHE_PATH = "data/snapshots/hooklist/hooklist.json"

# hooklist camelCase flag name -> our SCREAMING_SNAKE permission name.
FLAG_NAME_MAP: dict[str, str] = {
    "beforeInitialize": "BEFORE_INITIALIZE",
    "afterInitialize": "AFTER_INITIALIZE",
    "beforeAddLiquidity": "BEFORE_ADD_LIQUIDITY",
    "afterAddLiquidity": "AFTER_ADD_LIQUIDITY",
    "beforeRemoveLiquidity": "BEFORE_REMOVE_LIQUIDITY",
    "afterRemoveLiquidity": "AFTER_REMOVE_LIQUIDITY",
    "beforeSwap": "BEFORE_SWAP",
    "afterSwap": "AFTER_SWAP",
    "beforeDonate": "BEFORE_DONATE",
    "afterDonate": "AFTER_DONATE",
    "beforeSwapReturnsDelta": "BEFORE_SWAP_RETURNS_DELTA",
    "afterSwapReturnsDelta": "AFTER_SWAP_RETURNS_DELTA",
    "afterAddLiquidityReturnsDelta": "AFTER_ADD_LIQUIDITY_RETURNS_DELTA",
    "afterRemoveLiquidityReturnsDelta": "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA",
}


@dataclass(frozen=True)
class HooklistEntry:
    address: str
    chain: str
    chain_id: int | None
    name: str
    description: str
    deployer: str
    verified_source: bool
    audit_url: str
    flags: dict[str, bool]
    dynamic_fee: bool
    upgradeable: bool
    requires_custom_swap_data: bool
    vanilla_swap: bool
    swap_access: str

    @property
    def claimed_bitmap(self) -> int:
        """The permission bitmap the registry claims, rebuilt from its booleans.

        Compared against the bitmap decoded from the address: they must agree, because v4
        derives permissions from the address and nothing else.
        """
        bits = 0
        for camel, on in self.flags.items():
            name = FLAG_NAME_MAP.get(camel)
            if name and on:
                bits |= FLAGS[name]
        return bits


def cache_path() -> Path:
    return repo_root() / CACHE_PATH


def fetch(*, force: bool = False, timeout: float = 120.0) -> Path:
    """Download `hooklist.json` into the snapshot directory, unless already cached."""
    path = cache_path()
    if path.is_file() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(HOOKLIST_URL)
        response.raise_for_status()
        path.write_bytes(response.content)
    return path


def _entry(raw: dict[str, Any]) -> HooklistEntry:
    hook = raw.get("hook", {})
    props = raw.get("properties", {})
    return HooklistEntry(
        address=normalize(hook["address"]),
        chain=str(hook.get("chain", "")),
        chain_id=hook.get("chainId"),
        name=str(hook.get("name", "")),
        description=str(hook.get("description", "")),
        deployer=str(hook.get("deployer", "")),
        verified_source=bool(hook.get("verifiedSource", False)),
        audit_url=str(hook.get("auditUrl", "")),
        flags={k: bool(v) for k, v in (raw.get("flags") or {}).items()},
        dynamic_fee=bool(props.get("dynamicFee", False)),
        upgradeable=bool(props.get("upgradeable", False)),
        requires_custom_swap_data=bool(props.get("requiresCustomSwapData", False)),
        vanilla_swap=bool(props.get("vanillaSwap", False)),
        swap_access=str(props.get("swapAccess", "")),
    )


def load(path: Path | None = None) -> list[HooklistEntry]:
    path = path or cache_path()
    if not path.is_file():
        raise FileNotFoundError(f"hooklist not cached at {path}; call fetch() first")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [_entry(item) for item in raw]


def by_chain_and_address(
    entries: list[HooklistEntry] | None = None,
) -> dict[tuple[int, str], HooklistEntry]:
    """Join key for the census: `(chain_id, lowercase address)`.

    The same hook address is deployed on several chains with different behaviour, so
    address alone is not a key.
    """
    entries = entries if entries is not None else load()
    out: dict[tuple[int, str], HooklistEntry] = {}
    for e in entries:
        if e.chain_id is None:
            continue
        out[(int(e.chain_id), e.address)] = e
    return out
