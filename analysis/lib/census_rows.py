"""Turn decoded `Initialize` events into the census row shape, in one place.

Both the streaming compactor and the pipeline build the same rows, so the definition
lives here rather than being duplicated and drifting.
"""

from __future__ import annotations

from typing import Any

from .events import InitializeEvent
from .hookflags import bitmap, names, returns_delta, touches_swap

COLUMNS = (
    "pool_id",
    "currency0",
    "currency1",
    "fee",
    "dynamic_fee",
    "tick_spacing",
    "hook",
    "hookless",
    "flags_bitmap",
    "touches_swap",
    "returns_delta",
    "permissions",
    "block_number",
    "tx_hash",
    "log_index",
)


def row(event: InitializeEvent) -> dict[str, Any]:
    hookless = event.hookless
    return {
        "pool_id": event.pool_id,
        "currency0": event.currency0,
        "currency1": event.currency1,
        "fee": event.fee,
        "dynamic_fee": event.dynamic_fee,
        "tick_spacing": event.tick_spacing,
        "hook": event.hooks,
        "hookless": hookless,
        "flags_bitmap": 0 if hookless else bitmap(event.hooks),
        "touches_swap": (not hookless) and touches_swap(event.hooks),
        "returns_delta": (not hookless) and returns_delta(event.hooks),
        "permissions": "" if hookless else "|".join(names(event.hooks)),
        "block_number": event.block_number,
        "tx_hash": event.tx_hash,
        "log_index": event.log_index,
    }
