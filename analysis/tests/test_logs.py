"""Adaptive log fetching: back off on provider limits, resume after a crash.

A census pull is hours long and spans tens of millions of blocks. Both failure modes here
are silent and catastrophic — a skipped range quietly shrinks the denominator for every
downstream number — so they are tested rather than observed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sworn_analysis.lib.logs import (
    MIN_CHUNK,
    LogFetcher,
    fetch_to_jsonl,
    iter_logs,
    looks_like_range_limit,
    resume_point,
)
from sworn_analysis.lib.rpc import RpcError


class LimitedRpc:
    """A provider that refuses any range wider than `max_span` blocks."""

    def __init__(self, max_span: int, logs_per_block: int = 0, error: str | None = None) -> None:
        self.max_span = max_span
        self.logs_per_block = logs_per_block
        self.error = error or "query returned more than 10000 results"
        self.requests: list[tuple[int, int]] = []

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        assert method == "eth_getLogs"
        f = int(params[0]["fromBlock"], 16)  # type: ignore[index]
        t = int(params[0]["toBlock"], 16)  # type: ignore[index]
        span = t - f + 1
        if span > self.max_span:
            raise RpcError("eth_getLogs", -32600, self.error)
        self.requests.append((f, t))
        return [
            {"blockNumber": hex(b)} for b in range(f, t + 1) for _ in range(self.logs_per_block)
        ]


def test_range_limit_phrases_are_recognised() -> None:
    for message in (
        "query returned more than 10000 results",
        "Under the Free tier plan, you can make eth_getLogs requests with up to a 10 block range",
        "block range is too large",
        "exceeds the maximum block range",
        "response size exceeded",
    ):
        assert looks_like_range_limit(RpcError("eth_getLogs", -32600, message)), message


def test_unrelated_errors_are_not_treated_as_limits() -> None:
    # Retrying these would silently produce an incomplete census.
    assert not looks_like_range_limit(RpcError("eth_getLogs", -32000, "unauthorized"))
    assert not looks_like_range_limit(RpcError("eth_getLogs", -32601, "method not found"))


def test_timeouts_count_as_a_reason_to_shrink() -> None:
    assert looks_like_range_limit(httpx.ReadTimeout("slow"))


def test_fetcher_backs_off_to_the_provider_limit() -> None:
    rpc = LimitedRpc(max_span=10)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=10_000)  # type: ignore[arg-type]
    list(fetcher.fetch_range(0, 99))
    assert fetcher.stats.backoffs > 0
    assert fetcher.stats.max_chunk_used <= 10


def test_fetched_ranges_are_contiguous_and_complete() -> None:
    rpc = LimitedRpc(max_span=64)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=1000)  # type: ignore[arg-type]
    covered = [(lo, hi) for lo, hi, _ in fetcher.fetch_range(1000, 1500)]

    assert covered[0][0] == 1000
    assert covered[-1][1] == 1500
    for (_, prev_hi), (next_lo, _) in zip(covered, covered[1:], strict=False):
        assert next_lo == prev_hi + 1, "gap or overlap in coverage"


def test_chunk_grows_again_after_sustained_success() -> None:
    rpc = LimitedRpc(max_span=1_000_000)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=100)  # type: ignore[arg-type]
    list(fetcher.fetch_range(0, 100_000))
    assert fetcher.chunk > 100


def test_chunk_never_goes_below_the_floor() -> None:
    rpc = LimitedRpc(max_span=1)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=64)  # type: ignore[arg-type]
    with pytest.raises(RpcError):
        list(fetcher.fetch_range(0, 100))
    assert fetcher.chunk >= MIN_CHUNK


def test_resume_point_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert resume_point(tmp_path / "nope.jsonl") is None


def test_resume_skips_completed_ranges(tmp_path: Path) -> None:
    out = tmp_path / "pull.jsonl"
    rpc = LimitedRpc(max_span=1_000_000, logs_per_block=1)

    fetch_to_jsonl(rpc, "0xpm", [], 0, 499, out, start_chunk=500)  # type: ignore[arg-type]
    first_pass = list(rpc.requests)

    rpc.requests.clear()
    fetch_to_jsonl(rpc, "0xpm", [], 0, 999, out, start_chunk=500)  # type: ignore[arg-type]

    assert first_pass, "first pass made no requests"
    assert all(lo >= 500 for lo, _ in rpc.requests), "resume re-requested completed blocks"
    assert len(list(iter_logs(out))) == 1000


def test_resume_tolerates_a_torn_final_line(tmp_path: Path) -> None:
    # A process killed mid-write leaves a partial JSON line; everything before it is good.
    out = tmp_path / "pull.jsonl"
    out.write_text(
        json.dumps({"_from": 0, "_to": 99, "logs": [{"blockNumber": "0x1"}]})
        + "\n"
        + '{"_from": 100, "_to',
        encoding="utf-8",
    )
    assert resume_point(out) == 99
    assert len(list(iter_logs(out))) == 1


def test_nothing_to_do_when_already_complete(tmp_path: Path) -> None:
    out = tmp_path / "pull.jsonl"
    out.write_text(json.dumps({"_from": 0, "_to": 999, "logs": []}) + "\n", encoding="utf-8")
    rpc = LimitedRpc(max_span=1_000)
    stats = fetch_to_jsonl(rpc, "0xpm", [], 0, 999, out)  # type: ignore[arg-type]
    assert stats.chunks == 0
    assert rpc.requests == []


class RateLimitedRpc:
    """Refuses the first `fail_times` requests with 429, then succeeds."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.attempts = 0
        self.served: list[tuple[int, int]] = []

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            request = httpx.Request("POST", "https://node.example/v2/key")
            response = httpx.Response(429, text="rate limited", request=request)
            raise httpx.HTTPStatusError("429", request=request, response=response)
        f = int(params[0]["fromBlock"], 16)  # type: ignore[index]
        t = int(params[0]["toBlock"], 16)  # type: ignore[index]
        self.served.append((f, t))
        return []


def test_rate_limit_is_waited_out_not_shrunk() -> None:
    from sworn_analysis.lib.logs import is_rate_limit

    rpc = RateLimitedRpc(fail_times=2)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=1000)  # type: ignore[arg-type]
    slept: list[float] = []
    fetcher._sleep = slept.append  # type: ignore[method-assign]

    list(fetcher.fetch_range(0, 999))

    assert slept == [1.0, 2.0], "should back off exponentially"
    assert fetcher.chunk == 1000, "a 429 must not shrink the window"
    assert fetcher.stats.backoffs == 0
    assert rpc.served == [(0, 999)]
    assert is_rate_limit(
        httpx.HTTPStatusError(
            "429",
            request=httpx.Request("POST", "https://x"),
            response=httpx.Response(429, request=httpx.Request("POST", "https://x")),
        )
    )


def test_413_is_a_size_refusal_whatever_the_body() -> None:
    # QuickNode answers with a 413 whose body is not JSON-RPC at all.
    request = httpx.Request("POST", "https://node.example/v2/key")
    response = httpx.Response(413, text="<html>Request Entity Too Large</html>", request=request)
    exc = httpx.HTTPStatusError("413", request=request, response=response)
    assert looks_like_range_limit(exc)


def test_rate_limit_gives_up_after_the_retry_budget() -> None:
    rpc = RateLimitedRpc(fail_times=99)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=1000)  # type: ignore[arg-type]
    fetcher._sleep = lambda _s: None  # type: ignore[method-assign]
    with pytest.raises(httpx.HTTPStatusError):
        list(fetcher.fetch_range(0, 999))


def test_fetcher_does_not_retry_a_width_already_refused() -> None:
    """Growth must remember the ceiling.

    Without this the fetcher pays one refused request every GROWTH_AFTER chunks for the
    whole run — thousands of wasted calls across a 26M-block census.
    """
    rpc = LimitedRpc(max_span=10_000)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=10_000)  # type: ignore[arg-type]
    list(fetcher.fetch_range(0, 2_000_000))

    # One probe above the limit is expected; a cycle would produce dozens.
    assert fetcher.stats.backoffs <= 2, f"thrashing: {fetcher.stats.backoffs} backoffs"
    assert fetcher.stats.max_chunk_used <= 10_000


def test_ceiling_still_allows_growth_from_a_low_start() -> None:
    rpc = LimitedRpc(max_span=10_000)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=100)  # type: ignore[arg-type]
    list(fetcher.fetch_range(0, 500_000))
    assert fetcher.chunk > 100


def test_gzipped_pull_roundtrips(tmp_path: Path) -> None:
    """Raw pulls are hundreds of MB per chain; gzip is what keeps them on disk."""
    out = tmp_path / "pull.jsonl.gz"
    rpc = LimitedRpc(max_span=1_000_000, logs_per_block=2)

    fetch_to_jsonl(rpc, "0xpm", [], 0, 99, out, start_chunk=100)  # type: ignore[arg-type]

    assert out.is_file()
    assert out.read_bytes()[:2] == b"\x1f\x8b", "not actually gzipped"
    assert len(list(iter_logs(out))) == 200
    assert resume_point(out) == 99


def test_gzipped_pull_resumes(tmp_path: Path) -> None:
    out = tmp_path / "pull.jsonl.gz"
    rpc = LimitedRpc(max_span=1_000_000, logs_per_block=1)

    fetch_to_jsonl(rpc, "0xpm", [], 0, 49, out, start_chunk=50)  # type: ignore[arg-type]
    rpc.requests.clear()
    fetch_to_jsonl(rpc, "0xpm", [], 0, 99, out, start_chunk=50)  # type: ignore[arg-type]

    assert all(lo >= 50 for lo, _ in rpc.requests)
    assert len(list(iter_logs(out))) == 100


class FlakyRpc:
    """Fails the first `fail_times` requests with a 503, then succeeds."""

    def __init__(self, fail_times: int, status: int = 503) -> None:
        self.fail_times = fail_times
        self.status = status
        self.attempts = 0
        self.served: list[tuple[int, int]] = []

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            request = httpx.Request("POST", "https://node.example/v2/key")
            response = httpx.Response(self.status, text="Service Unavailable", request=request)
            raise httpx.HTTPStatusError("503", request=request, response=response)
        f = int(params[0]["fromBlock"], 16)  # type: ignore[index]
        t = int(params[0]["toBlock"], 16)  # type: ignore[index]
        self.served.append((f, t))
        return []


def test_transient_server_errors_are_retried_not_fatal() -> None:
    """A multi-hour pull will meet a 5xx; losing the whole chain to one is unacceptable.

    This is not hypothetical: the BNB census died at 10.6% on a QuickNode 503.
    """
    from sworn_analysis.lib.logs import is_transient

    rpc = FlakyRpc(fail_times=3)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=1000)  # type: ignore[arg-type]
    slept: list[float] = []
    fetcher._sleep = slept.append  # type: ignore[method-assign]

    list(fetcher.fetch_range(0, 999))

    assert slept == [2.0, 4.0, 8.0], "should back off exponentially"
    assert fetcher.chunk == 1000, "a 5xx says nothing about request size"
    assert fetcher.stats.backoffs == 0
    assert rpc.served == [(0, 999)]
    assert is_transient(
        httpx.HTTPStatusError(
            "502",
            request=httpx.Request("POST", "https://x"),
            response=httpx.Response(502, request=httpx.Request("POST", "https://x")),
        )
    )


def test_transient_retries_are_bounded() -> None:
    rpc = FlakyRpc(fail_times=99)
    fetcher = LogFetcher(rpc, "0xpm", [], start_chunk=1000)  # type: ignore[arg-type]
    fetcher._sleep = lambda _s: None  # type: ignore[method-assign]
    with pytest.raises(httpx.HTTPStatusError):
        list(fetcher.fetch_range(0, 999))


def test_a_413_is_still_a_size_refusal_not_a_transient_error() -> None:
    from sworn_analysis.lib.logs import is_transient

    request = httpx.Request("POST", "https://node.example/v2/key")
    response = httpx.Response(413, text="too large", request=request)
    exc = httpx.HTTPStatusError("413", request=request, response=response)
    assert not is_transient(exc)
    assert looks_like_range_limit(exc)


def test_node_side_rpc_errors_are_retried() -> None:
    """Observed in a real pull: Polygon returned this mid-census and killed the chain."""
    from sworn_analysis.lib.logs import is_transient

    for message in (
        "failed to get logs for block #74592117 (0xc67aff..299d09)",
        "missing trie node",
        "header not found",
    ):
        exc = RpcError("eth_getLogs", -32000, message)
        assert is_transient(exc), message
        # And must not be mistaken for a size refusal, which would shrink the window.
        assert not looks_like_range_limit(exc), message


def test_a_genuine_error_is_still_fatal() -> None:
    from sworn_analysis.lib.logs import is_transient

    exc = RpcError("eth_getLogs", -32000, "unauthorized")
    assert not is_transient(exc)
    assert not looks_like_range_limit(exc)
