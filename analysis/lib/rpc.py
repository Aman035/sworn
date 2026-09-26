"""Minimal JSON-RPC client and capability probing.

Sworn needs more than "an RPC that answers". Phase 3 re-quotes fills against historical
state and Phase 4 proves an opcode executed on the swap path, so an endpoint that serves
`eth_blockNumber` but not archive state or `debug_traceCall` will fail deep into a long
run rather than at the start. `check_endpoint` is what turns that into an up-front error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Chain

DEFAULT_TIMEOUT = 30.0

# How far back to ask for state. Deep enough that a pruned node cannot answer from its
# recent-state window, shallow enough to exist on a young chain.
ARCHIVE_DEPTH_BLOCKS = 250_000

# The log window Phase 2 wants to sweep in one request.
LOG_WINDOW_BLOCKS = 10_000


class RpcError(RuntimeError):
    """A JSON-RPC error response, carrying the provider's own message."""

    def __init__(self, method: str, code: int, message: str) -> None:
        super().__init__(f"{method}: [{code}] {message}")
        self.method = method
        self.code = code
        self.rpc_message = message


def redact(url: str) -> str:
    """Host plus a short path fingerprint. Never the API key.

    Every diagnostic in this repo prints endpoints through here, because RPC URLs embed
    credentials in the path and these strings end up in logs and phase docs.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<unparseable url>"
    host = parsed.netloc or "<no host>"
    tail = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not tail:
        return host
    return f"{host}/…{tail[-4:]}" if len(tail) > 4 else f"{host}/…"


class RpcClient:
    def __init__(self, url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.url = url
        self._client = httpx.Client(timeout=timeout)
        self._id = 0

    def __enter__(self) -> RpcClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}
        response = self._client.post(self.url, json=payload)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            err = body["error"]
            raise RpcError(method, int(err.get("code", 0)), str(err.get("message", "")))
        return body["result"]

    def chain_id(self) -> int:
        return int(self.call("eth_chainId"), 16)

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber"), 16)


@dataclass
class Capability:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class EndpointReport:
    chain: str
    url_redacted: str
    reachable: bool
    chain_id: int | None = None
    expected_chain_id: int | None = None
    latest_block: int | None = None
    capabilities: list[Capability] = field(default_factory=list)
    error: str = ""

    @property
    def chain_id_matches(self) -> bool:
        return self.chain_id is not None and self.chain_id == self.expected_chain_id

    @property
    def ok(self) -> bool:
        return self.reachable and self.chain_id_matches and all(c.ok for c in self.capabilities)

    def missing(self) -> list[str]:
        return [c.name for c in self.capabilities if not c.ok]


def scrub(text: str, url: str) -> str:
    """Remove the endpoint URL (which carries the API key) from provider error text.

    httpx puts the full request URL in its exception messages, and those messages end up
    in gate logs and phase docs. Scrubbing here rather than at each call site means a new
    probe cannot forget to do it.
    """
    cleaned = text.replace(url, redact(url))
    key = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    if len(key) > 6:
        cleaned = cleaned.replace(key, "…" + key[-4:])
    return cleaned


def _probe(name: str, url: str, fn: Any) -> Capability:
    try:
        detail = fn()
    except RpcError as exc:
        return Capability(name, False, scrub(exc.rpc_message, url)[:200])
    except httpx.HTTPStatusError as exc:
        # Providers put the real reason in the body; the status line alone is useless.
        body = exc.response.text.strip().replace("\n", " ")
        return Capability(name, False, scrub(f"HTTP {exc.response.status_code}: {body}", url)[:200])
    except httpx.HTTPError as exc:
        return Capability(name, False, scrub(f"http: {exc}", url)[:200])
    return Capability(name, True, str(detail)[:160])


def check_endpoint(
    chain: Chain, url: str | None = None, timeout: float = DEFAULT_TIMEOUT
) -> EndpointReport:
    """Probe one endpoint for everything Sworn will need from it."""
    url = url or os.environ.get(chain.rpc_env, "")
    report = EndpointReport(
        chain=chain.name,
        url_redacted=redact(url) if url else "(unset)",
        reachable=False,
        expected_chain_id=chain.chain_id,
    )
    if not url:
        report.error = f"{chain.rpc_env} is not set"
        return report

    try:
        with RpcClient(url, timeout=timeout) as rpc:
            report.chain_id = rpc.chain_id()
            report.latest_block = rpc.block_number()
            report.reachable = True

            latest = report.latest_block
            old_block = hex(max(1, latest - ARCHIVE_DEPTH_BLOCKS))

            report.capabilities = [
                _probe(
                    "archive_state",
                    url,
                    lambda: "balance at -{} = {}".format(
                        ARCHIVE_DEPTH_BLOCKS,
                        rpc.call(
                            "eth_getBalance",
                            ["0x0000000000000000000000000000000000000000", old_block],
                        ),
                    ),
                ),
                _probe(
                    "eth_call_historical",
                    url,
                    lambda: rpc.call(
                        "eth_call",
                        [
                            {"to": "0x0000000000000000000000000000000000000000", "data": "0x"},
                            old_block,
                        ],
                    )
                    or "0x",
                ),
                _probe(
                    f"eth_getLogs_{LOG_WINDOW_BLOCKS}_blocks",
                    url,
                    lambda: "{} logs".format(
                        len(
                            rpc.call(
                                "eth_getLogs",
                                [
                                    {
                                        "fromBlock": hex(max(1, latest - LOG_WINDOW_BLOCKS)),
                                        "toBlock": hex(latest),
                                        # A topic nothing emits: we are measuring the range
                                        # limit, not pulling data.
                                        "topics": [
                                            "0x" + "ee" * 32,
                                        ],
                                    }
                                ],
                            )
                        )
                    ),
                ),
                _probe(
                    "debug_traceCall",
                    url,
                    lambda: str(
                        rpc.call(
                            "debug_traceCall",
                            [
                                {"to": "0x0000000000000000000000000000000000000000", "data": "0x"},
                                "latest",
                                {"tracer": "callTracer"},
                            ],
                        )
                    )[:60],
                ),
            ]
    except httpx.HTTPError as exc:
        report.error = scrub(f"http: {exc}", url)
    except RpcError as exc:
        report.error = scrub(str(exc), url)
    except ValueError as exc:
        report.error = scrub(f"bad response: {exc}", url)
    return report
