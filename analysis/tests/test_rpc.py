"""RPC helpers, with particular attention to never printing an API key.

RPC URLs carry credentials in the path, and these strings land in gate logs and phase
docs that get committed. The redaction is therefore tested like a security control, not
like a formatting nicety.
"""

from __future__ import annotations

import httpx
import pytest
from sworn_analysis.lib.rpc import (
    Capability,
    EndpointReport,
    RpcClient,
    RpcError,
    _probe,
    redact,
    scrub,
)

# A synthetic key shaped like a real one. Never paste a live credential into a test:
# it would be committed, and the redaction under test exists precisely to stop that.
KEY = "alch_EXAMPLEkeyDoNotUse0000"
URL = f"https://unichain-mainnet.g.alchemy.com/v2/{KEY}"


def test_redact_keeps_host_and_hides_key() -> None:
    out = redact(URL)
    assert "unichain-mainnet.g.alchemy.com" in out
    assert KEY not in out
    assert out.endswith(KEY[-4:])


def test_redact_handles_url_without_path() -> None:
    assert redact("https://bsc-dataseed.binance.org") == "bsc-dataseed.binance.org"


def test_redact_handles_empty_input() -> None:
    assert redact("") == "<no host>"


def test_scrub_removes_full_url_and_bare_key() -> None:
    message = f"Client error '400 Bad Request' for url '{URL}'. Key {KEY} rejected"
    out = scrub(message, URL)
    assert KEY not in out
    assert URL not in out
    assert "400 Bad Request" in out


def test_scrub_leaves_unrelated_text_alone() -> None:
    assert scrub("plain message", URL) == "plain message"


def test_probe_scrubs_a_status_error() -> None:
    request = httpx.Request("POST", URL)
    response = httpx.Response(400, text='{"error":{"message":"not on Free tier"}}', request=request)

    def boom() -> str:
        raise httpx.HTTPStatusError("bad", request=request, response=response)

    cap = _probe("debug_traceCall", URL, boom)
    assert not cap.ok
    assert KEY not in cap.detail
    # The provider's own reason survives: that is the whole point of reading the body.
    assert "not on Free tier" in cap.detail


def test_probe_scrubs_an_rpc_error() -> None:
    def boom() -> str:
        raise RpcError("eth_getLogs", -32600, f"range too wide for {URL}")

    cap = _probe("eth_getLogs", URL, boom)
    assert not cap.ok
    assert KEY not in cap.detail


def test_probe_records_success_detail() -> None:
    cap = _probe("archive_state", URL, lambda: "0x1234")
    assert cap.ok
    assert cap.detail == "0x1234"


def test_rpc_client_raises_on_json_rpc_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nope"}}
        )

    client = RpcClient(URL)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(RpcError) as exc:
        client.call("eth_chainId")
    assert exc.value.code == -32000
    assert exc.value.rpc_message == "nope"


def test_rpc_client_parses_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x2105"})

    client = RpcClient(URL)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert client.chain_id() == 8453


def test_report_ok_requires_chain_id_match() -> None:
    report = EndpointReport(
        chain="base",
        url_redacted="host/…abcd",
        reachable=True,
        chain_id=1,
        expected_chain_id=8453,
        capabilities=[Capability("archive_state", True)],
    )
    assert not report.ok
    assert not report.chain_id_matches


def test_report_missing_lists_failed_capabilities() -> None:
    report = EndpointReport(
        chain="unichain",
        url_redacted="host/…abcd",
        reachable=True,
        chain_id=130,
        expected_chain_id=130,
        capabilities=[
            Capability("archive_state", True),
            Capability("debug_traceCall", False, "not on Free tier"),
        ],
    )
    assert not report.ok
    assert report.missing() == ["debug_traceCall"]


def test_unset_endpoint_reports_the_variable_name() -> None:
    from sworn_analysis.lib.config import chain

    report = EndpointReport(chain="base", url_redacted="(unset)", reachable=False)
    assert not report.ok
    assert chain("base").rpc_env == "BASE_RPC_ARCHIVE"
