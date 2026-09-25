"""Recover the `hookData` a router actually passed, from the transaction's own trace.

`expected_output` must quote the *identical* swap, and `hookData` is part of that swap: a
hook free to price on it is a hook that will be measured against a call it never received
if the field is guessed.

Decoding router calldata was the obvious approach and is the wrong one — it needs a
decoder per router, every router encodes differently, and the two Universal Router
deployments on Base do not even use the standard `execute` selector. Tracing the
transaction and reading the argument the PoolManager was actually handed is
router-agnostic, works for routers nobody has catalogued, and costs about 0.1 s per fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_utils import keccak

from .rpc import RpcClient, RpcError

# PoolManager.swap(PoolKey, SwapParams, bytes)
SWAP_SELECTOR = (
    "0x"
    + keccak(text="swap((address,address,uint24,int24,address),(bool,int256,uint160),bytes)").hex()[
        :8
    ]
)

# Head layout of that calldata: 5 PoolKey words, 3 SwapParams words, then the offset to
# the dynamic `hookData` tail.
HOOKDATA_OFFSET_WORD = 8


@dataclass(frozen=True)
class RecoveredHookData:
    tx_hash: str
    #: Index of the PoolManager.swap call within the transaction, in trace order. A
    #: multi-hop route makes several, and they line up with the Swap events in order.
    call_index: int
    pool_id_words: tuple[str, ...]
    hook_data: str
    ok: bool
    error: str = ""


def _words(hex_body: str) -> list[str]:
    return [hex_body[i : i + 64] for i in range(0, len(hex_body), 64)]


def decode_hook_data(calldata: str) -> str:
    """Pull `hookData` out of a `PoolManager.swap` calldata blob."""
    if not calldata.startswith(SWAP_SELECTOR):
        raise ValueError("not a PoolManager.swap call")
    words = _words(calldata[10:])
    if len(words) <= HOOKDATA_OFFSET_WORD:
        raise ValueError("calldata too short for a swap call")

    offset = int(words[HOOKDATA_OFFSET_WORD], 16)
    index = offset // 32
    if index >= len(words):
        raise ValueError("hookData offset points past the calldata")

    length = int(words[index], 16)
    if length == 0:
        return "0x"

    body = "".join(words[index + 1 :])
    return "0x" + body[: length * 2]


def _walk(node: dict[str, Any], out: list[dict[str, Any]]) -> None:
    if str(node.get("input", "")).startswith(SWAP_SELECTOR):
        out.append(node)
    for child in node.get("calls") or []:
        _walk(child, out)


def recover(rpc: RpcClient, tx_hash: str) -> list[RecoveredHookData]:
    """Every `PoolManager.swap` in one transaction, with the hookData each received."""
    try:
        trace = rpc.call(
            "debug_traceTransaction",
            [tx_hash, {"tracer": "callTracer", "tracerConfig": {"withLog": False}}],
        )
    except RpcError as exc:
        return [RecoveredHookData(tx_hash, 0, (), "0x", False, str(exc)[:120])]

    calls: list[dict[str, Any]] = []
    _walk(trace, calls)

    recovered: list[RecoveredHookData] = []
    for i, call in enumerate(calls):
        calldata = str(call.get("input", ""))
        try:
            hook_data = decode_hook_data(calldata)
        except ValueError as exc:
            recovered.append(RecoveredHookData(tx_hash, i, (), "0x", False, str(exc)))
            continue
        words = tuple(_words(calldata[10:])[:5])
        recovered.append(RecoveredHookData(tx_hash, i, words, hook_data, True))
    return recovered
