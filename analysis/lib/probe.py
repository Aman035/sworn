"""hook-probe. Differential and trace-based detection of spoof-capable hooks.

Three methods, with very different failure modes, which is the point: Phase 4's job is to
report where each one *fails*, not to produce a single verdict.

* **static** (`lib/evm.py`). Does the bytecode contain an environment opcode? Cheap,
  complete, and nearly useless alone: 99.2% of Base hooks contain one.
* **differential**. Quote the same swap under different `tx.gasprice`, caller and gas,
  and see whether the answer moves. State is identical across permutations, so anything
  that changes is environment sensitivity by definition.
* **trace**. `debug_traceCall` with a tracer that records only environment opcodes and
  the contract that executed them. This is what turns "contains ORIGIN" into "the hook
  reads ORIGIN while pricing the swap".

The quoter is injected with an `eth_call` state override rather than looked up on-chain,
so probing does not depend on a deployed `V4Quoter` and always uses the version pinned in
this repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from eth_abi.abi import encode as abi_encode
from eth_utils import keccak

from .config import repo_root
from .rpc import RpcClient, RpcError

# A scratch address to host the injected quoter. Nothing may exist here.
QUOTER_SLOT = "0x00000000000000000000000000000000000c0de0"
PROBE_CALLER_EOA = "0x000000000000000000000000000000000000beef"

# Environment opcodes that can distinguish a simulation from a real transaction.
# `GAS`, `TIMESTAMP`, `NUMBER` and `CHAINID` are excluded deliberately: solc emits `GAS`
# for every external call, so including them would flag almost every contract.
DISTINGUISHING_OPCODES = ("GASPRICE", "ORIGIN", "COINBASE", "PREVRANDAO", "BASEFEE", "GASLIMIT")

# Opcodes that transfer control to another contract. Used to reconstruct which address
# is executing at each depth, so an environment read can be attributed to the hook rather
# than to the PoolManager or a library.
CALL_OPCODES = ("CALL", "CALLCODE", "STATICCALL", "DELEGATECALL")


def selector(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()[:8]


QUOTE_EXACT_INPUT_SINGLE = selector(
    "quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))"
)


@dataclass
class Permutation:
    """One environment the same swap is quoted under."""

    label: str
    gas_price_wei: int
    from_address: str
    gas: int


DEFAULT_PERMUTATIONS = (
    # Zero gas price is what an `eth_call` looks like: the canonical simulator tell.
    Permutation("simulator", 0, PROBE_CALLER_EOA, 30_000_000),
    Permutation("real-1gwei", 1_000_000_000, PROBE_CALLER_EOA, 30_000_000),
    Permutation("real-100gwei", 100_000_000_000, PROBE_CALLER_EOA, 30_000_000),
    # Half the gas: catches hooks keyed on gas headroom rather than price.
    Permutation("low-gas", 1_000_000_000, PROBE_CALLER_EOA, 1_500_000),
)


@dataclass
class ProbeResult:
    address: str
    chain: str
    env_sensitive: bool = False
    max_disagreement_bps: float = 0.0
    signals: list[str] = field(default_factory=list)
    outputs: dict[str, int | None] = field(default_factory=dict)
    reverted: dict[str, bool] = field(default_factory=dict)
    env_opcodes_on_path: list[str] = field(default_factory=list)
    trace_available: bool = False
    error: str = ""


@lru_cache(maxsize=4)
def quoter_creation_code() -> str:
    """V4Quoter's creation bytecode from the Foundry build."""
    artifact = repo_root() / "contracts" / "out" / "V4Quoter.sol" / "V4Quoter.json"
    if not artifact.is_file():
        raise FileNotFoundError(f"build contracts first: {artifact} missing")
    return json.loads(artifact.read_text(encoding="utf-8"))["bytecode"]["object"]


def quoter_runtime_code(rpc: RpcClient, pool_manager: str) -> str:
    """Run the quoter's constructor on the node and keep the runtime code it returns.

    The quoter stores its `PoolManager` as an immutable, so the runtime code differs per
    chain. Executing the constructor via `eth_call` with no `to` gives exactly the code
    that would be deployed, without deploying anything.
    """
    args = abi_encode(["address"], [pool_manager]).hex()
    return rpc.call("eth_call", [{"data": quoter_creation_code() + args}, "latest"])


def encode_quote_call(
    currency0: str,
    currency1: str,
    fee: int,
    tick_spacing: int,
    hooks: str,
    zero_for_one: bool,
    amount: int,
    hook_data: str = "0x",
) -> str:
    # A hook that prices on `hookData` and is quoted with empty bytes is being asked a
    # different question than the one the router asked, so the real bytes are recovered
    # from the transaction (see `lib/swapcalls.py`) and passed through.
    payload = abi_encode(
        ["((address,address,uint24,int24,address),bool,uint128,bytes)"],
        [
            (
                (currency0, currency1, fee, tick_spacing, hooks),
                zero_for_one,
                amount,
                bytes.fromhex(hook_data[2:]),
            )
        ],
    )
    return QUOTE_EXACT_INPUT_SINGLE + payload.hex()


def _quote_under(
    rpc: RpcClient,
    runtime_code: str,
    call_data: str,
    permutation: Permutation,
    block: str = "latest",
) -> tuple[int | None, bool]:
    """Returns (amountOut, reverted). The quoter reverts to return its answer, so a
    revert here is the *normal* path and the payload carries the number."""
    overrides = {QUOTER_SLOT: {"code": runtime_code}}
    tx = {
        "to": QUOTER_SLOT,
        "from": permutation.from_address,
        "data": call_data,
        "gas": hex(permutation.gas),
        "gasPrice": hex(permutation.gas_price_wei),
    }
    try:
        out = rpc.call("eth_call", [tx, block, overrides])
    except RpcError:
        return None, True
    if not out or out == "0x":
        return None, True
    # quoteExactInputSingle returns (amountOut, gasEstimate)
    raw = out[2:]
    if len(raw) < 64:
        return None, True
    return int(raw[:64], 16), False


def differential_probe(
    rpc: RpcClient,
    chain: str,
    pool_manager: str,
    pool: dict[str, Any],
    amount: int,
    *,
    permutations: tuple[Permutation, ...] = DEFAULT_PERMUTATIONS,
    disagreement_bps: float = 1.0,
    runtime_code: str | None = None,
) -> ProbeResult:
    """Quote the same swap under several environments and compare."""
    result = ProbeResult(address=pool["hook"], chain=chain)
    try:
        code = runtime_code or quoter_runtime_code(rpc, pool_manager)
    except (RpcError, FileNotFoundError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"[:160]
        return result

    call_data = encode_quote_call(
        pool["currency0"],
        pool["currency1"],
        int(pool["fee"]),
        int(pool["tick_spacing"]),
        pool["hook"],
        True,
        amount,
    )

    for p in permutations:
        out, reverted = _quote_under(rpc, code, call_data, p)
        result.outputs[p.label] = out
        result.reverted[p.label] = reverted

    usable = [v for v in result.outputs.values() if v is not None and v > 0]
    if len(usable) >= 2:
        lo, hi = min(usable), max(usable)
        result.max_disagreement_bps = (hi - lo) / hi * 10_000 if hi else 0.0
        if result.max_disagreement_bps > disagreement_bps:
            result.env_sensitive = True
            result.signals.append("differential-disagreement")

    # A hook that reverts only for some environments is gating on them just as surely as
    # one that prices differently.
    reverts = {k for k, v in result.reverted.items() if v}
    if reverts and len(reverts) < len(result.reverted):
        result.env_sensitive = True
        result.signals.append(f"revert-gated:{','.join(sorted(reverts))}")

    return result


def attribute_opcodes(struct_logs: list[dict[str, Any]], entry_address: str) -> list[str]:
    """Attribute each environment opcode to the contract that executed it.

    `debug_traceCall`'s struct logger reports an opcode and a depth but not an address, so
    the executing contract is reconstructed from the call stack: on a CALL-family opcode
    the callee sits second-from-top of the EVM stack, and everything at the next depth
    runs in that contract until the depth drops back.

    This is the whole point of trace mode. 99.2% of Base hooks *contain* an environment
    opcode; what matters is whether the hook runs one while pricing a swap.
    """
    frames: dict[int, str] = {1: entry_address.lower()}
    pending_target: str | None = None
    found: list[str] = []

    for log in struct_logs:
        depth = int(log.get("depth", 1))
        op = str(log.get("op", ""))

        if pending_target is not None:
            # The first entry at a deeper level belongs to the contract just called.
            frames[depth] = pending_target
            pending_target = None

        if op in DISTINGUISHING_OPCODES or op == "DIFFICULTY":
            name = "PREVRANDAO" if op == "DIFFICULTY" else op
            found.append(f"{name}@{frames.get(depth, 'unknown')}")

        if op in CALL_OPCODES:
            stack = log.get("stack") or []
            if len(stack) >= 2:
                # Callee is second from the top; stack is reported bottom-to-top.
                pending_target = "0x" + str(stack[-2])[-40:].lower()

    return found


def trace_env_opcodes(
    rpc: RpcClient,
    pool_manager: str,
    pool: dict[str, Any],
    amount: int,
    *,
    runtime_code: str | None = None,
    gas_price_wei: int = 1_000_000_000,
) -> tuple[list[str], bool]:
    """Which environment opcodes actually execute while pricing this swap, and where.

    Uses the built-in struct logger rather than a custom JS tracer: JS tracers are
    disabled on some providers (QuickNode returns "JS Tracer is not enabled"), and the
    struct logger is available everywhere `debug_traceCall` is. Memory and storage are
    disabled to keep the response manageable; the stack is needed for attribution.

    Returns (entries like "GASPRICE@0xhook", trace_available).
    """
    try:
        code = runtime_code or quoter_runtime_code(rpc, pool_manager)
    except (RpcError, FileNotFoundError):
        return [], False

    call_data = encode_quote_call(
        pool["currency0"],
        pool["currency1"],
        int(pool["fee"]),
        int(pool["tick_spacing"]),
        pool["hook"],
        True,
        amount,
    )
    tx = {
        "to": QUOTER_SLOT,
        "from": PROBE_CALLER_EOA,
        "data": call_data,
        "gas": hex(30_000_000),
        "gasPrice": hex(gas_price_wei),
    }
    try:
        raw = rpc.call(
            "debug_traceCall",
            [
                tx,
                "latest",
                {
                    "disableMemory": True,
                    "disableStorage": True,
                    "disableStack": False,
                    "stateOverrides": {QUOTER_SLOT: {"code": code}},
                },
            ],
        )
    except RpcError:
        return [], False

    logs = raw.get("structLogs") if isinstance(raw, dict) else None
    if not isinstance(logs, list):
        return [], False
    return attribute_opcodes(logs, QUOTER_SLOT), True


def on_swap_path(entries: list[str], hook: str) -> list[str]:
    """Environment opcodes executed *by the hook itself*.

    An opcode executed by the PoolManager or a library says nothing about the hook. This
    is the distinction that separates a 38.3% static signal from a real finding.
    """
    hook = hook.lower()
    found = []
    for e in entries:
        op, _, addr = e.partition("@")
        if addr.lower() == hook and op in DISTINGUISHING_OPCODES:
            found.append(op)
    return sorted(set(found))
