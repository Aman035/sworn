"""Etherscan response parsing, against real captured responses.

The `Proxy` field is the trap: it is not a boolean. Etherscan returns "2" for a proxy it
detected on an *unverified* contract, which is precisely the case for the Base hook 0x
named, so a `== "1"` test reports the most interesting hook in the dataset as
non-upgradeable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sworn_analysis.lib.etherscan import (
    EtherscanClient,
    EtherscanError,
    _parse,
    _trim,
)

# Captured from api.etherscan.io on 2026-09-25.
BASE_HOOK_UNVERIFIED_PROXY = {
    "status": "1",
    "result": [
        {
            "ContractName": "",
            "CompilerVersion": "",
            "Proxy": "2",
            "Implementation": "0x22c38c800f50d55c1365a35f66f970f16f1f3c83",
            "LicenseType": "Unknown",
            "ABI": "Contract source code not verified",
        }
    ],
}

BNB_HOOK_UNVERIFIED_PLAIN = {
    "status": "1",
    "result": [
        {
            "ContractName": "",
            "CompilerVersion": "",
            "Proxy": "0",
            "Implementation": "",
            "LicenseType": "Unknown",
            "ABI": "Contract source code not verified",
        }
    ],
}

VERIFIED_PLAIN = {
    "status": "1",
    "result": [
        {
            "ContractName": "BunniHook",
            "CompilerVersion": "v0.8.26+commit.8a97fa7a",
            "Proxy": "0",
            "Implementation": "",
            "LicenseType": "MIT",
            "ABI": '[{"inputs":[],"name":"foo"',
        }
    ],
}

VERIFIED_PROXY = {
    "status": "1",
    "result": [
        {
            "ContractName": "TransparentUpgradeableProxy",
            "CompilerVersion": "v0.8.26+commit.8a97fa7a",
            "Proxy": "1",
            "Implementation": "0x1111111111111111111111111111111111111111",
            "LicenseType": "MIT",
            "ABI": '[{"inputs":[]',
        }
    ],
}


def test_unverified_proxy_is_detected_as_upgradeable() -> None:
    """Proxy == "2" must count. This is the hook 0x named."""
    info = _parse(BASE_HOOK_UNVERIFIED_PROXY, 8453, "0x800cef53c3fd41109dffec62e5251bdd7acba5c7")
    assert not info.verified
    assert info.proxy
    assert info.upgradeable_by_proxy
    assert info.implementation == "0x22c38c800f50d55c1365a35f66f970f16f1f3c83"


def test_unverified_non_proxy() -> None:
    info = _parse(BNB_HOOK_UNVERIFIED_PLAIN, 56, "0x141984423d1a28242b3dd8888c5b0daa7b13c880")
    assert not info.verified
    assert not info.proxy
    assert not info.upgradeable_by_proxy


def test_verified_contract() -> None:
    info = _parse(VERIFIED_PLAIN, 42161, "0x" + "ab" * 20)
    assert info.verified
    assert info.name == "BunniHook"
    assert not info.proxy


def test_verified_proxy() -> None:
    info = _parse(VERIFIED_PROXY, 1, "0x" + "cd" * 20)
    assert info.verified
    assert info.proxy
    assert info.upgradeable_by_proxy


def test_implementation_alone_implies_proxy() -> None:
    body = json.loads(json.dumps(BASE_HOOK_UNVERIFIED_PROXY))
    body["result"][0]["Proxy"] = "0"
    assert _parse(body, 8453, "0x" + "11" * 20).proxy


def test_empty_result_is_unverified_not_an_error() -> None:
    info = _parse({"status": "0", "result": []}, 8453, "0x" + "22" * 20)
    assert not info.verified
    assert not info.proxy


def test_trim_drops_source_but_keeps_signals() -> None:
    fat = {
        "status": "1",
        "result": [
            {
                "SourceCode": "x" * 5_000_000,
                "ABI": "Contract source code not verified",
                "ContractName": "",
                "CompilerVersion": "",
                "Proxy": "2",
                "Implementation": "0x" + "ab" * 20,
                "LicenseType": "Unknown",
            }
        ],
    }
    slim = _trim(fat)
    assert "SourceCode" not in slim["result"][0]
    assert slim["result"][0]["Proxy"] == "2"
    assert len(json.dumps(slim)) < 1000
    # The trimmed form must still parse to the same conclusions.
    assert _parse(slim, 8453, "0x" + "ab" * 20).upgradeable_by_proxy


def test_missing_api_key_fails_loudly() -> None:
    with pytest.raises(EtherscanError, match="ETHERSCAN_KEY"):
        EtherscanClient("")


def test_cached_responses_on_disk_still_parse() -> None:
    """Whatever is already cached must remain readable by the current parser."""
    from sworn_analysis.lib.etherscan import cache_dir

    root: Path = cache_dir()
    if not root.is_dir():
        pytest.skip("no etherscan cache yet")
    files = list(root.rglob("*.json"))[:20]
    if not files:
        pytest.skip("cache is empty")
    for path in files:
        body = json.loads(path.read_text(encoding="utf-8"))
        info = _parse(body, int(path.parent.name), path.stem)
        assert info.address == path.stem
