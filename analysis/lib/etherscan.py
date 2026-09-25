"""Etherscan V2 client: verified source and proxy metadata for hook contracts.

One key covers every supported chain via `?chainid=`. The census needs three things from
it — is the source verified, is the contract a proxy, and what is it called — and none of
them are available from an RPC node.

Rate limits are the operative constraint: the free tier allows a few calls per second and
a census has tens of thousands of hooks, so every response is cached on disk and the
client paces itself. A cached census re-run costs no API calls at all.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import repo_root

API_URL = "https://api.etherscan.io/v2/api"
CACHE_DIR = "data/cache/etherscan"

# Free tier is 5 calls/second. Stay under it: a 429 costs more than the pause.
# Etherscan's free tier enforces 3/sec and rejects the burst, not just the average.
# Pace below it: a 429 costs a retry, and the retry costs more than the pause.
DEFAULT_RATE_PER_SEC = 2.5

# Etherscan uses a string status field rather than HTTP codes for logical failures.
STATUS_OK = "1"


class EtherscanError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContractInfo:
    address: str
    chain_id: int
    verified: bool
    name: str = ""
    compiler: str = ""
    proxy: bool = False
    implementation: str = ""
    license: str = ""

    @property
    def upgradeable_by_proxy(self) -> bool:
        """Etherscan's own proxy determination, which is independent of our slot probing."""
        return self.proxy or bool(self.implementation)


def cache_dir() -> Path:
    return repo_root() / CACHE_DIR


def _cache_path(chain_id: int, address: str) -> Path:
    return cache_dir() / str(chain_id) / f"{address.lower()}.json"


class EtherscanClient:
    def __init__(
        self,
        api_key: str,
        *,
        rate_per_sec: float = DEFAULT_RATE_PER_SEC,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise EtherscanError("ETHERSCAN_KEY is not set")
        self.api_key = api_key
        self._min_interval = 1.0 / max(0.1, rate_per_sec)
        self._last_call = 0.0
        self._client = httpx.Client(timeout=timeout)
        self.api_calls = 0
        self.cache_hits = 0

    def __enter__(self) -> EtherscanClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _pace(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, params: dict[str, Any], *, attempts: int = 4) -> Any:
        """One request, retrying a rate-limit rejection rather than aborting the sweep.

        Etherscan reports throttling as HTTP 200 with `status: "0"`, so it has to be read
        from the body. Losing a multi-thousand-hook metadata run to one burst would be a
        poor trade for a one-second pause.
        """
        last = ""
        for attempt in range(attempts):
            self._pace()
            self.api_calls += 1
            response = self._client.get(API_URL, params={**params, "apikey": self.api_key})
            response.raise_for_status()
            body = response.json()
            result = str(body.get("result", "")).lower()
            if body.get("status") == STATUS_OK or "rate limit" not in result:
                return body
            last = str(body.get("result", ""))
            time.sleep(self._min_interval * (2 ** (attempt + 1)))
        raise EtherscanError(f"rate limited after {attempts} attempts: {last}")

    def source(self, chain_id: int, address: str, *, use_cache: bool = True) -> ContractInfo:
        """`getsourcecode` for one contract, cached on disk by (chain, address)."""
        address = address.lower()
        path = _cache_path(chain_id, address)

        if use_cache and path.is_file():
            self.cache_hits += 1
            return _parse(json.loads(path.read_text(encoding="utf-8")), chain_id, address)

        body = self._get(
            {
                "chainid": chain_id,
                "module": "contract",
                "action": "getsourcecode",
                "address": address,
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # Source text can be megabytes and is not needed downstream; keep the metadata.
        trimmed = _trim(body)
        path.write_text(json.dumps(trimmed), encoding="utf-8")
        return _parse(trimmed, chain_id, address)


def _trim(body: dict[str, Any]) -> dict[str, Any]:
    """Drop the source blob, keep the fields the census uses."""
    result = body.get("result")
    if not isinstance(result, list) or not result:
        return {"status": body.get("status"), "result": []}
    entry = result[0]
    keep = ("ContractName", "CompilerVersion", "Proxy", "Implementation", "LicenseType", "ABI")
    slim = {k: entry.get(k, "") for k in keep}
    # `ABI` is only kept as the verification signal; "Contract source code not verified"
    # is what Etherscan returns for unverified contracts.
    slim["ABI"] = str(slim.get("ABI", ""))[:64]
    return {"status": body.get("status"), "result": [slim]}


def _parse(body: dict[str, Any], chain_id: int, address: str) -> ContractInfo:
    result = body.get("result")
    if not isinstance(result, list) or not result:
        return ContractInfo(address=address, chain_id=chain_id, verified=False)

    entry = result[0]
    abi = str(entry.get("ABI", ""))
    verified = bool(entry.get("ContractName")) and not abi.startswith(
        "Contract source code not verified"
    )

    # `Proxy` is not a boolean. Etherscan returns "0" for no proxy, "1" for a verified
    # proxy, and "2" for one it detected on an *unverified* contract — which is exactly
    # the case for the Base hook 0x named. Testing `== "1"` silently misses those, so
    # anything non-zero counts, and a populated `Implementation` counts on its own.
    proxy_field = str(entry.get("Proxy", "0")).strip()
    implementation = str(entry.get("Implementation", "")).strip().lower()
    is_proxy = (proxy_field not in ("", "0")) or bool(implementation)

    return ContractInfo(
        address=address,
        chain_id=chain_id,
        verified=verified,
        name=str(entry.get("ContractName", "")),
        compiler=str(entry.get("CompilerVersion", "")),
        proxy=is_proxy,
        implementation=implementation,
        license=str(entry.get("LicenseType", "")),
    )
