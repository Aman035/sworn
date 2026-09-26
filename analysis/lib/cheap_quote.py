"""The cheap re-quote path: `eth_call` at block N-1 instead of a fork.

`docs/METRICS.md` defines two ways to compute `expected_output`:

* **exact**. `vm.rollFork(txHash)`, which gives the state after every earlier transaction
  in the fill's own block. Correct whenever another swap in the same block moved the pool,
  and it costs roughly 33 seconds per fill because the fork downloads the state the swap
  touches.
* **approx**. `eth_call` against a quoter at the end of block `N-1`. Wrong by exactly the
  amount that earlier same-block transactions moved the pool, and about 600 times faster.

At 33 s/fill a ten-thousand-fill study is four days of wall time, so the exact method
cannot answer population-level questions on its own. This module provides the cheap path;
`compare_methods` measures how far apart the two actually are, so the error is reported
rather than assumed away.

The quoter is injected with an `eth_call` state override, so nothing needs deploying and
the pinned periphery is always what answers.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from .probe import QUOTER_SLOT, encode_quote_call, quoter_runtime_code
from .requote import RequoteInput
from .rpc import RpcClient

# How many `eth_call`s to put in one JSON-RPC batch. Large enough to amortise the round
# trip, small enough that one oversized response does not lose the whole batch.
BATCH_SIZE = 40
DEFAULT_WORKERS = 6


@dataclass(frozen=True)
class CheapQuote:
    tx_hash: str
    log_index: int
    expected: int
    block: int
    ok: bool
    error: str = ""


def _call_payload(idx: int, code: str, fill: RequoteInput, block: int) -> dict[str, Any]:
    data = encode_quote_call(
        fill.currency0,
        fill.currency1,
        fill.fee,
        fill.tick_spacing,
        fill.hooks,
        fill.zero_for_one,
        fill.amount_specified,
        fill.hook_data,
    )
    return {
        "jsonrpc": "2.0",
        "id": idx,
        "method": "eth_call",
        "params": [
            {"to": QUOTER_SLOT, "data": data, "gas": hex(60_000_000)},
            hex(block),
            {QUOTER_SLOT: {"code": code}},
        ],
    }


def _decode(result: str | None) -> int | None:
    """quoteExactInputSingle returns (amountOut, gasEstimate)."""
    if not result or result == "0x":
        return None
    raw = result[2:]
    if len(raw) < 64:
        return None
    try:
        return int(raw[:64], 16)
    except ValueError:
        return None


def _run_batch(
    url: str, code: str, chunk: list[tuple[RequoteInput, int]], timeout: float
) -> list[CheapQuote]:
    payload = [_call_payload(i, code, f, b) for i, (f, b) in enumerate(chunk)]
    out: list[CheapQuote] = []

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        # One failed batch must not lose the run; the fills are simply marked unusable and
        # counted, so a degraded endpoint shows up as coverage loss rather than as zeros.
        return [
            CheapQuote(f.tx_hash, f.log_index, 0, b, False, f"batch: {type(exc).__name__}")
            for f, b in chunk
        ]

    by_id = {int(r["id"]): r for r in body} if isinstance(body, list) else {}
    for i, (fill, block) in enumerate(chunk):
        entry = by_id.get(i)
        if entry is None or "error" in entry:
            message = (
                str(entry.get("error", {}).get("message", "no result")) if entry else "no result"
            )
            out.append(CheapQuote(fill.tx_hash, fill.log_index, 0, block, False, message[:120]))
            continue
        amount = _decode(entry.get("result"))
        if amount is None or amount == 0:
            out.append(CheapQuote(fill.tx_hash, fill.log_index, 0, block, False, "empty quote"))
            continue
        out.append(CheapQuote(fill.tx_hash, fill.log_index, amount, block, True))
    return out


def quote_many(
    url: str,
    pool_manager: str,
    fills: Iterable[tuple[RequoteInput, int]],
    *,
    workers: int = DEFAULT_WORKERS,
    batch_size: int = BATCH_SIZE,
    timeout: float = 120.0,
    progress: Any = None,
) -> list[CheapQuote]:
    """Quote every `(fill, block)` pair. `block` is the block to quote at, normally N-1."""
    pairs = list(fills)
    if not pairs:
        return []

    with RpcClient(url, timeout=60) as rpc:
        code = quoter_runtime_code(rpc, pool_manager)

    chunks = [pairs[i : i + batch_size] for i in range(0, len(pairs), batch_size)]
    results: list[CheapQuote] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_batch, url, code, c, timeout) for c in chunks]
        for n, future in enumerate(futures, start=1):
            results.extend(future.result())
            if progress:
                progress(n, len(chunks), len(results))
    return results


@dataclass
class MethodAgreement:
    compared: int
    within_tolerance: int
    median_abs_bps: float
    p90_abs_bps: float
    max_abs_bps: float
    tolerance_bps: float

    @property
    def agreement_rate(self) -> float:
        return self.within_tolerance / self.compared if self.compared else 0.0


def compare_methods(
    exact: dict[tuple[str, int], int],
    cheap: dict[tuple[str, int], int],
    *,
    tolerance_bps: float,
) -> MethodAgreement:
    """How far the cheap method sits from the exact one, on fills both could quote.

    Published rather than assumed: the cheap method is wrong by exactly the amount earlier
    same-block transactions moved the pool, and that error is a property of the chain's
    block composition, not something a docstring can bound.
    """
    import statistics

    deviations: list[float] = []
    for key, exact_amount in exact.items():
        cheap_amount = cheap.get(key)
        if cheap_amount is None or exact_amount <= 0:
            continue
        deviations.append(abs(cheap_amount - exact_amount) / exact_amount * 10_000)

    if not deviations:
        return MethodAgreement(0, 0, 0.0, 0.0, 0.0, tolerance_bps)

    deviations.sort()
    within = sum(1 for d in deviations if d <= tolerance_bps)
    return MethodAgreement(
        compared=len(deviations),
        within_tolerance=within,
        median_abs_bps=statistics.median(deviations),
        p90_abs_bps=deviations[max(0, int(0.9 * len(deviations)) - 1)],
        max_abs_bps=deviations[-1],
        tolerance_bps=tolerance_bps,
    )
