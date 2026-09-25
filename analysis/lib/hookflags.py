"""Decode Uniswap v4 hook permissions from the hook address.

v4 encodes a hook's permissions in the low 14 bits of its own address — that is why hook
deployments are mined with CREATE2 salts. Constants mirror
`contracts/lib/v4-core/src/libraries/Hooks.sol` at the pinned tag `v4.0.0`; the Phase 2
gate checks the two agree by parsing that file, so a dependency bump cannot silently
desynchronise them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .config import repo_root

ALL_HOOK_MASK = (1 << 14) - 1

# Bit position -> permission name, highest bit first (as in Hooks.sol).
FLAGS: dict[str, int] = {
    "BEFORE_INITIALIZE": 1 << 13,
    "AFTER_INITIALIZE": 1 << 12,
    "BEFORE_ADD_LIQUIDITY": 1 << 11,
    "AFTER_ADD_LIQUIDITY": 1 << 10,
    "BEFORE_REMOVE_LIQUIDITY": 1 << 9,
    "AFTER_REMOVE_LIQUIDITY": 1 << 8,
    "BEFORE_SWAP": 1 << 7,
    "AFTER_SWAP": 1 << 6,
    "BEFORE_DONATE": 1 << 5,
    "AFTER_DONATE": 1 << 4,
    "BEFORE_SWAP_RETURNS_DELTA": 1 << 3,
    "AFTER_SWAP_RETURNS_DELTA": 1 << 2,
    "AFTER_ADD_LIQUIDITY_RETURNS_DELTA": 1 << 1,
    "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA": 1 << 0,
}

# The permissions that let a hook change what a swapper receives. Everything Sworn
# measures is about these four; a hook without any of them cannot take from a swap.
SWAP_RELEVANT = (
    "BEFORE_SWAP",
    "AFTER_SWAP",
    "BEFORE_SWAP_RETURNS_DELTA",
    "AFTER_SWAP_RETURNS_DELTA",
)

HOOKS_SOL = "contracts/lib/v4-core/src/libraries/Hooks.sol"


class InvalidAddressError(ValueError):
    """Raised for anything that is not a 20-byte hex address."""


def normalize(address: str) -> str:
    a = address.strip().lower()
    if not a.startswith("0x"):
        a = "0x" + a
    if not re.fullmatch(r"0x[0-9a-f]{40}", a):
        raise InvalidAddressError(f"not a 20-byte address: {address!r}")
    return a


def bitmap(address: str) -> int:
    """The 14-bit permission bitmap carried by the address itself."""
    return int(normalize(address), 16) & ALL_HOOK_MASK


def permissions(address: str) -> dict[str, bool]:
    bits = bitmap(address)
    return {name: bool(bits & mask) for name, mask in FLAGS.items()}


def names(address: str) -> list[str]:
    """Set permissions, in Hooks.sol order — stable output for snapshots and diffs."""
    bits = bitmap(address)
    return [name for name, mask in FLAGS.items() if bits & mask]


def has_any(address: str, flags: tuple[str, ...]) -> bool:
    bits = bitmap(address)
    return any(bits & FLAGS[f] for f in flags)


def touches_swap(address: str) -> bool:
    """Whether the hook runs on the swap path at all."""
    return has_any(address, SWAP_RELEVANT)


def returns_delta(address: str) -> bool:
    """Whether the hook can change swap amounts, not merely observe them.

    This is the capability that makes quote spoofing possible: a hook with only
    BEFORE_SWAP can revert or adjust the fee, but a hook with the returns-delta
    permissions can take an arbitrary share of the swap.
    """
    return has_any(address, ("BEFORE_SWAP_RETURNS_DELTA", "AFTER_SWAP_RETURNS_DELTA"))


def is_hookless(address: str) -> bool:
    """The zero address means the pool has no hook. It is the calibration baseline."""
    return int(normalize(address), 16) == 0


@dataclass(frozen=True)
class HookFlags:
    address: str
    bitmap: int
    names: tuple[str, ...]
    touches_swap: bool
    returns_delta: bool

    @classmethod
    def of(cls, address: str) -> HookFlags:
        addr = normalize(address)
        return cls(
            address=addr,
            bitmap=bitmap(addr),
            names=tuple(names(addr)),
            touches_swap=touches_swap(addr),
            returns_delta=returns_delta(addr),
        )


@lru_cache(maxsize=1)
def flags_from_solidity() -> dict[str, int]:
    """Parse the flag constants straight out of the pinned Hooks.sol.

    Used by the Phase 2 gate: if a v4-core bump renumbers a bit, the census would
    mislabel every hook, so the two definitions are compared rather than trusted.
    """
    src = (repo_root() / HOOKS_SOL).read_text(encoding="utf-8")
    pattern = re.compile(r"uint160\s+internal\s+constant\s+([A-Z_]+)_FLAG\s*=\s*1\s*<<\s*(\d+);")
    return {name: 1 << int(shift) for name, shift in pattern.findall(src)}
