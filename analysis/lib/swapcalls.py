"""Recover what a swap actually did, from the transaction's own trace.

**The `Swap` event does not say what the user received.** `PoolManager.swap` runs
`beforeSwap`, executes the swap on whatever amount that hook left, emits the event for
*that* swap, and only then runs `afterSwap`, which may take more. The event is emitted
between the two hook calls, deliberately, so that events stay ordered:

    beforeSwap  ->  may reduce the amount swapped
    _swap       ->  emits Swap(amount0, amount1)   <-- what indexers read
    afterSwap   ->  may take a further delta
    accounting  ->  what the caller is actually charged

Measured on Base: a hook taking 1% in `afterSwap` shows an event `amount1` of
3,941,355,102,139,778,949 while the caller received 3,901,941,551,118,381,160. Reading
the event, that hook looks like it *gave* the user 1% extra. It took 1%.

The consequence is not a rounding detail. Anyone measuring hook behaviour from `Swap`
events — the obvious approach, and the one this repo started with — systematically
under-reports exactly the hooks that take the most, because taking in `afterSwap` is
invisible to the event.

What this module recovers instead, from `debug_traceTransaction` at ~0.01 s per
transaction:

* `amount_specified` — what the router asked for, before any hook touched it
* `hook_data` — what the hook was actually handed
* `delta0` / `delta1` — the swap's **return value**, after `afterSwap`

Those three are the identical-swap definition `docs/METRICS.md` requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_utils import keccak

from .rpc import RpcClient, RpcError

SWAP_SELECTOR = (
    "0x"
    + keccak(text="swap((address,address,uint24,int24,address),(bool,int256,uint160),bytes)").hex()[
        :8
    ]
)

# Calldata head: currency0, currency1, fee, tickSpacing, hooks, zeroForOne,
# amountSpecified, sqrtPriceLimitX96, then the offset to the dynamic hookData tail.
W_ZERO_FOR_ONE = 5
W_AMOUNT_SPECIFIED = 6
W_HOOKDATA_OFFSET = 8


def _to_int256(word: str) -> int:
    value = int(word, 16)
    return value - (1 << 256) if value >= (1 << 255) else value


def _to_int128(value: int) -> int:
    return value - (1 << 128) if value >= (1 << 127) else value


def _words(body: str) -> list[str]:
    return [body[i : i + 64] for i in range(0, len(body), 64)]


@dataclass(frozen=True)
class SwapCall:
    tx_hash: str
    #: Position among the PoolManager.swap calls in this transaction, in trace order.
    #: Swap events are emitted in the same order, which is how the two are matched.
    index: int
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str
    zero_for_one: bool
    amount_specified: int
    hook_data: str
    #: The call's return value: the caller's delta *after* afterSwap.
    delta0: int
    delta1: int
    ok: bool
    error: str = ""
    #: The ABI encoding of the pool key, kept so `pool_id` needs no re-decode.
    _key_words: str = ""

    @property
    def pool_id(self) -> str:
        """`keccak256(abi.encode(poolKey))`, the same id the `Swap` event carries.

        The five key fields are all static, so their ABI encoding is exactly the first
        five words of the swap calldata — matching a traced call to an indexed fill needs
        no guessing about trace ordering.
        """
        head = bytes.fromhex(self._key_words)
        return "0x" + keccak(head).hex()

    @property
    def amount_in(self) -> int:
        """What the caller actually paid, from the post-hook delta."""
        d = self.delta0 if self.zero_for_one else self.delta1
        return -d if d < 0 else 0

    @property
    def amount_out(self) -> int:
        """What the caller actually received, from the post-hook delta."""
        d = self.delta1 if self.zero_for_one else self.delta0
        return d if d > 0 else 0


def _decode_call(tx_hash: str, index: int, node: dict[str, Any]) -> SwapCall:
    calldata = str(node.get("input", ""))
    words = _words(calldata[10:])
    if len(words) <= W_HOOKDATA_OFFSET:
        return SwapCall(
            tx_hash, index, "", "", 0, 0, "", False, 0, "0x", 0, 0, False, "short calldata"
        )

    offset = int(words[W_HOOKDATA_OFFSET], 16) // 32
    hook_data = "0x"
    if offset < len(words):
        length = int(words[offset], 16)
        if length:
            hook_data = "0x" + "".join(words[offset + 1 :])[: length * 2]

    output = str(node.get("output", "") or "")
    if not output or output == "0x":
        # Without the return value there is no honest "realized" amount, so the call is
        # marked unusable rather than silently falling back to the event.
        return SwapCall(
            tx_hash, index, "", "", 0, 0, "", False, 0, hook_data, 0, 0, False, "no return data"
        )

    packed = int(output, 16)
    return SwapCall(
        tx_hash=tx_hash,
        index=index,
        currency0="0x" + words[0][-40:],
        currency1="0x" + words[1][-40:],
        fee=int(words[2], 16),
        tick_spacing=_to_int256(words[3]),
        hooks="0x" + words[4][-40:],
        zero_for_one=int(words[W_ZERO_FOR_ONE], 16) == 1,
        amount_specified=_to_int256(words[W_AMOUNT_SPECIFIED]),
        hook_data=hook_data,
        _key_words="".join(words[:5]),
        delta0=_to_int128(packed >> 128),
        delta1=_to_int128(packed & ((1 << 128) - 1)),
        ok=True,
    )


def _walk(node: dict[str, Any], out: list[dict[str, Any]]) -> None:
    if str(node.get("input", "")).startswith(SWAP_SELECTOR):
        out.append(node)
    for child in node.get("calls") or []:
        _walk(child, out)


def recover(rpc: RpcClient, tx_hash: str) -> list[SwapCall]:
    """Every `PoolManager.swap` in one transaction, as it actually happened."""
    try:
        trace = rpc.call(
            "debug_traceTransaction",
            [tx_hash, {"tracer": "callTracer", "tracerConfig": {"withLog": False}}],
        )
    except RpcError as exc:
        return [SwapCall(tx_hash, 0, "", "", 0, 0, "", False, 0, "0x", 0, 0, False, str(exc)[:120])]

    nodes: list[dict[str, Any]] = []
    _walk(trace, nodes)
    return [_decode_call(tx_hash, i, n) for i, n in enumerate(nodes)]


def recover_many(
    url: str,
    tx_hashes: list[str],
    *,
    workers: int = 8,
    timeout: float = 90.0,
) -> dict[str, list[SwapCall]]:
    """`recover` over many transactions, keyed by hash. Duplicates are traced once."""
    from concurrent.futures import ThreadPoolExecutor

    unique = list(dict.fromkeys(tx_hashes))

    def one(tx: str) -> tuple[str, list[SwapCall]]:
        with RpcClient(url, timeout=timeout) as rpc:
            return tx, recover(rpc, tx)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, unique))


def pool_id_of(currency0: str, currency1: str, fee: int, tick_spacing: int, hooks: str) -> str:
    """The `PoolId` for a key, so an indexed fill can be matched to a traced call."""
    from eth_abi import encode as abi_encode

    return (
        "0x"
        + keccak(
            abi_encode(
                ["(address,address,uint24,int24,address)"],
                [(currency0, currency1, fee, tick_spacing, hooks)],
            )
        ).hex()
    )
