"""PoolManager registry and deployment-block search.

The census start block is load-bearing: too late and the denominator is silently
truncated, too early and the run wastes hours. The binary search is therefore tested
against a synthetic chain rather than trusted against a live one.
"""

from __future__ import annotations

from typing import Any

import pytest
from sworn_analysis.lib.config import chains
from sworn_analysis.lib.deployments import (
    INITIALIZE_TOPIC,
    POOL_MANAGERS,
    SWAP_TOPIC,
    Deployment,
    code_size,
    find_deployment_block,
    has_code,
    load_deployments,
    pool_manager,
    verify_pool_manager,
)


class FakeRpc:
    """A chain where `address` gained code at `deployed_at` and nothing else exists."""

    def __init__(self, deployed_at: int, height: int, code: str = "0x" + "60" * 100) -> None:
        self.deployed_at = deployed_at
        self.height = height
        self.code = code
        self.calls = 0
        self.logs_error: Exception | None = None
        self.max_log_window = 10_000

    def block_number(self) -> int:
        return self.height

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        params = params or []
        if method == "eth_getCode":
            self.calls += 1
            tag = params[1]
            block = self.height if tag == "latest" else int(tag, 16)
            return self.code if block >= self.deployed_at else "0x"
        if method == "eth_getLogs":
            span = int(params[0]["toBlock"], 16) - int(params[0]["fromBlock"], 16)
            if span > self.max_log_window:
                raise RuntimeError(f"range {span} exceeds limit")
            return [{"topics": [INITIALIZE_TOPIC]}]
        raise AssertionError(f"unexpected method {method}")


def test_every_configured_chain_has_a_pool_manager() -> None:
    assert set(POOL_MANAGERS) == set(chains())


def test_pool_manager_addresses_are_well_formed() -> None:
    for name, addr in POOL_MANAGERS.items():
        assert addr.startswith("0x") and len(addr) == 42, name
        int(addr, 16)  # parses as hex


def test_unknown_chain_raises() -> None:
    with pytest.raises(KeyError, match="solana"):
        pool_manager("solana")


def test_event_topics_are_32_bytes() -> None:
    for topic in (INITIALIZE_TOPIC, SWAP_TOPIC):
        assert topic.startswith("0x") and len(topic) == 66


def test_find_deployment_block_is_exact() -> None:
    rpc = FakeRpc(deployed_at=25_350_988, height=51_000_000)
    assert find_deployment_block(rpc, "0xabc") == 25_350_988  # type: ignore[arg-type]


def test_find_deployment_block_handles_a_genesis_predeploy() -> None:
    # Unichain's PoolManager exists in genesis state, so block 0 is the right answer.
    rpc = FakeRpc(deployed_at=0, height=59_000_000)
    assert find_deployment_block(rpc, "0xabc") == 0  # type: ignore[arg-type]


def test_find_deployment_block_is_logarithmic() -> None:
    # A linear scan over a 500M-block chain would be unusable; keep it honest.
    rpc = FakeRpc(deployed_at=297_842_872, height=508_000_000)
    find_deployment_block(rpc, "0xabc")  # type: ignore[arg-type]
    assert rpc.calls < 40


def test_find_deployment_block_rejects_an_address_with_no_code() -> None:
    rpc = FakeRpc(deployed_at=10, height=5)
    with pytest.raises(ValueError, match="no code"):
        find_deployment_block(rpc, "0xabc")  # type: ignore[arg-type]


def test_has_code_and_code_size() -> None:
    rpc = FakeRpc(deployed_at=0, height=100)
    assert has_code(rpc, "0xabc")  # type: ignore[arg-type]
    assert code_size(rpc, "0xabc") == 100  # type: ignore[arg-type]


def test_verify_narrows_the_log_window_when_the_provider_refuses() -> None:
    # Alchemy's free tier caps eth_getLogs at 10 blocks; the check must still succeed.
    rpc = FakeRpc(deployed_at=0, height=1_000_000)
    rpc.max_log_window = 10
    ok, detail = verify_pool_manager(rpc, chains()["unichain"])  # type: ignore[arg-type]
    assert ok
    assert "9 blocks" in detail


def test_verify_fails_when_there_is_no_code() -> None:
    rpc = FakeRpc(deployed_at=10, height=5)
    ok, detail = verify_pool_manager(rpc, chains()["base"])  # type: ignore[arg-type]
    assert not ok
    assert "no code" in detail


def test_recorded_deployments_cover_every_chain_and_look_sane() -> None:
    recorded = load_deployments()
    assert set(recorded) == set(chains()), "run scripts/find_deployments.py"
    for name, d in recorded.items():
        assert isinstance(d, Deployment)
        assert d.pool_manager == POOL_MANAGERS[name]
        assert d.deployment_block >= 0
        # A real PoolManager is a large contract; anything tiny means a wrong address.
        assert d.code_size > 20_000, name
