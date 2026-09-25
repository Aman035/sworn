"""Decode the two v4 `PoolManager` events the census and divergence pipelines read.

Decoding is done here rather than with a generic ABI layer so the exact topic/data layout
is visible and testable: `Initialize` puts the pool id and both currencies in topics, and
everything else in data, and a mistake there mislabels every pool silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_abi.abi import decode as abi_decode

from .deployments import INITIALIZE_TOPIC, SWAP_TOPIC


class DecodeError(ValueError):
    """A log that does not match the expected v4 event layout."""


def _topic_address(topic: str) -> str:
    """A 32-byte topic holding a left-padded address."""
    raw = topic[2:] if topic.startswith("0x") else topic
    if len(raw) != 64:
        raise DecodeError(f"expected a 32-byte topic, got {len(raw) // 2} bytes")
    return "0x" + raw[-40:].lower()


def _hexint(value: str | int) -> int:
    return value if isinstance(value, int) else int(value, 16)


@dataclass(frozen=True)
class InitializeEvent:
    pool_id: str
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str
    sqrt_price_x96: int
    tick: int
    block_number: int
    tx_hash: str
    log_index: int

    @property
    def dynamic_fee(self) -> bool:
        """`0x800000` is the sentinel meaning "the hook decides the fee per swap"."""
        return self.fee == 0x800000

    @property
    def hookless(self) -> bool:
        return int(self.hooks, 16) == 0


@dataclass(frozen=True)
class SwapEvent:
    pool_id: str
    sender: str
    amount0: int
    amount1: int
    sqrt_price_x96: int
    liquidity: int
    tick: int
    fee: int
    block_number: int
    tx_hash: str
    log_index: int


def decode_initialize(log: dict[str, Any]) -> InitializeEvent:
    topics = log.get("topics") or []
    if len(topics) != 4 or topics[0].lower() != INITIALIZE_TOPIC:
        raise DecodeError(f"not an Initialize log: {len(topics)} topics")

    data = bytes.fromhex(log["data"][2:] if log["data"].startswith("0x") else log["data"])
    if len(data) != 160:
        raise DecodeError(f"Initialize data must be 5 words, got {len(data)} bytes")

    fee, tick_spacing, hooks, sqrt_price, tick = abi_decode(
        ["uint24", "int24", "address", "uint160", "int24"], data
    )

    return InitializeEvent(
        pool_id=topics[1].lower(),
        currency0=_topic_address(topics[2]),
        currency1=_topic_address(topics[3]),
        fee=int(fee),
        tick_spacing=int(tick_spacing),
        hooks=hooks.lower(),
        sqrt_price_x96=int(sqrt_price),
        tick=int(tick),
        block_number=_hexint(log["blockNumber"]),
        tx_hash=log["transactionHash"].lower(),
        log_index=_hexint(log["logIndex"]),
    )


def decode_swap(log: dict[str, Any]) -> SwapEvent:
    topics = log.get("topics") or []
    if len(topics) != 3 or topics[0].lower() != SWAP_TOPIC:
        raise DecodeError(f"not a Swap log: {len(topics)} topics")

    data = bytes.fromhex(log["data"][2:] if log["data"].startswith("0x") else log["data"])
    if len(data) != 192:
        raise DecodeError(f"Swap data must be 6 words, got {len(data)} bytes")

    amount0, amount1, sqrt_price, liquidity, tick, fee = abi_decode(
        ["int128", "int128", "uint160", "uint128", "int24", "uint24"], data
    )

    return SwapEvent(
        pool_id=topics[1].lower(),
        sender=_topic_address(topics[2]),
        amount0=int(amount0),
        amount1=int(amount1),
        sqrt_price_x96=int(sqrt_price),
        liquidity=int(liquidity),
        tick=int(tick),
        fee=int(fee),
        block_number=_hexint(log["blockNumber"]),
        tx_hash=log["transactionHash"].lower(),
        log_index=_hexint(log["logIndex"]),
    )
