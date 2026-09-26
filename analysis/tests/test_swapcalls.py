"""Recovering what a swap actually did, from its trace.

Two properties matter enough to pin down here, because both were real defects that took a
long measurement run to surface:

* the realized output must come from the call's **return value**, not the `Swap` event,
  because `PoolManager` emits that event before `afterSwap` and so omits the hook's take;
* every amount must survive a round trip through the on-disk cache. Swap amounts routinely
  exceed 2^63 and parquet has no int128, so an int column fails at write time, after the
  expensive tracing is already done.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from sworn_analysis.lib.swapcalls import SWAP_SELECTOR, SwapCall, pool_id_of, recover

WETH = "0x4200000000000000000000000000000000000006"
TOKEN = "0x1111111111111111111111111111111111111111"
HOOK = "0x03d2434d5a9ab7fb46bd3c7956a7c62e0cd46044"


def _word(value: int) -> str:
    return f"{value & (1 << 256) - 1:064x}"


def _calldata(amount_specified: int, hook_data: bytes = b"") -> str:
    head = "".join(
        [
            _word(int(TOKEN, 16)),
            _word(int(WETH, 16)),
            _word(3000),
            _word(60),
            _word(int(HOOK, 16)),
            _word(1),  # zeroForOne
            _word(amount_specified),
            _word(0),  # sqrtPriceLimitX96
            _word(9 * 32),  # offset to hookData
        ]
    )
    tail = _word(len(hook_data))
    if hook_data:
        padded = hook_data + b"\x00" * ((32 - len(hook_data) % 32) % 32)
        tail += padded.hex()
    return SWAP_SELECTOR + head + tail


def _output(delta0: int, delta1: int) -> str:
    packed = ((delta0 & (1 << 128) - 1) << 128) | (delta1 & (1 << 128) - 1)
    return "0x" + _word(packed)


class FakeRpc:
    """A node that returns one prepared trace. `url` is read only by the error path."""

    url = "https://node.example/redacted"

    def __init__(self, trace: dict[str, Any]) -> None:
        self.trace = trace

    def call(self, method: str, params: list[Any]) -> Any:
        assert method == "debug_traceTransaction"
        return self.trace


def test_realized_comes_from_the_return_value_not_the_event() -> None:
    """The observed Base case: a hook taking exactly 1% in `afterSwap`.

    The `Swap` event for this fill carried amount1 = 3,941,355,102,139,778,949. The call
    returned 3,901,941,551,118,381,160. Measuring from the event reports the hook as
    *paying* the user 1%.
    """
    requested = -19487100457704554985674870
    event_amount1 = 3941355102139778949
    true_amount1 = 3901941551118381160

    trace = {
        "input": "0x" + "00" * 4,
        "calls": [{"input": _calldata(requested), "output": _output(requested, true_amount1)}],
    }
    calls = recover(FakeRpc(trace), "0xdead")

    assert len(calls) == 1
    call = calls[0]
    assert call.ok
    assert call.amount_specified == requested
    assert call.amount_out == true_amount1
    assert call.amount_out != event_amount1

    # The gap is the hook's take, and it is exactly one percent of what the event showed.
    assert event_amount1 - true_amount1 == pytest.approx(event_amount1 * 0.01, rel=1e-9)


def test_exact_output_is_distinguishable_only_from_the_call() -> None:
    """A positive `amountSpecified` is exact-output; the event's signs look identical."""
    calls = recover(
        FakeRpc(
            {
                "input": "0x",
                "calls": [
                    {
                        "input": _calldata(9147424213421942),
                        "output": _output(-32724537430450108642002, 9147424213421942),
                    }
                ],
            }
        ),
        "0xbeef",
    )
    assert calls[0].amount_specified > 0


def test_hook_data_round_trips() -> None:
    payload = bytes(range(32))
    calls = recover(
        FakeRpc(
            {
                "input": "0x",
                "calls": [{"input": _calldata(-1000, payload), "output": _output(-1000, 900)}],
            }
        ),
        "0xfeed",
    )
    assert calls[0].hook_data == "0x" + payload.hex()


def test_pool_id_matches_the_calldata_head() -> None:
    """Matching an indexed fill to a traced call must need no ordering assumption."""
    calls = recover(
        FakeRpc({"input": "0x", "calls": [{"input": _calldata(-1), "output": _output(-1, 1)}]}),
        "0xaaaa",
    )
    assert calls[0].pool_id == pool_id_of(TOKEN, WETH, 3000, 60, HOOK)


def test_a_call_with_no_return_data_is_unusable_not_zero() -> None:
    """Without the return value there is no honest realized amount, so the row is dropped
    rather than silently measured as zero."""
    calls = recover(
        FakeRpc({"input": "0x", "calls": [{"input": _calldata(-1000), "output": "0x"}]}),
        "0xaaaa",
    )
    assert not calls[0].ok


def test_transport_failure_never_raises() -> None:
    """A ten-thousand-transaction run meets a dropped connection somewhere; losing the
    whole pass to it is not acceptable."""

    class Broken:
        url = "https://node.example/key"

        def call(self, *_: Any) -> Any:
            raise OSError("nodename nor servname provided")

    calls = recover(Broken(), "0xdead", attempts=2)
    assert not calls[0].ok
    assert "nodename" in calls[0].error


def test_amounts_survive_the_parquet_cache(tmp_path: Any) -> None:
    """The confirmed-sample cache is written after the expensive tracing, so an int64
    column would throw away the whole run. Amounts are stored as decimal strings."""
    big = 19487100457704554985674870
    assert big > 2**63

    frame = pd.DataFrame({"req_amount": [str(-big)], "realized": [str(big)]})
    path = tmp_path / "confirmed.parquet"
    frame.to_parquet(path, index=False)

    back = pd.read_parquet(path)
    assert int(back.req_amount[0]) == -big
    assert int(back.realized[0]) == big

    with pytest.raises((OverflowError, Exception)):
        pd.DataFrame({"realized": [big]}).to_parquet(tmp_path / "int.parquet", index=False)


def test_swap_call_defaults_are_unusable() -> None:
    assert not SwapCall("0x", 0, "", "", 0, 0, "", False, 0, "0x", 0, 0, False).ok
