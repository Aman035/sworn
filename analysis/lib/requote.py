"""Drive the Foundry re-quote script and read its answers back.

`expected_output` in `docs/METRICS.md` is the output the identical swap would have
produced against the state immediately before the fill. Only a fork can answer that, so
this module marshals fills into JSON, runs `contracts/script/Requote.s.sol`, and parses
the result.

The calibration rule is the reason this exists in a testable form: hookless pools must
come back with ~zero excess take. If they do not, the engine is wrong and every
downstream number is worthless, so the harness is built to make that check cheap to run
rather than to be run once by hand.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import repo_root
from .deployments import pool_manager

SCRIPT = "script/Requote.s.sol:RequoteScript"
CACHE_SUBDIR = "data/cache/requote"


@dataclass(frozen=True)
class RequoteInput:
    tx_hash: str
    log_index: int
    currency0: str
    currency1: str
    fee: int
    tick_spacing: int
    hooks: str
    zero_for_one: bool
    amount_specified: int  # magnitude of the exact input
    hook_data: str = "0x"

    def to_json(self) -> dict[str, Any]:
        return {
            "txHash": self.tx_hash,
            # A fill is (tx, log index), never tx alone: 37.8% of Base fills share a
            # transaction with another fill.
            "logIndex": self.log_index,
            "currency0": self.currency0,
            "currency1": self.currency1,
            "fee": self.fee,
            "tickSpacing": self.tick_spacing,
            "hooks": self.hooks,
            "zeroForOne": self.zero_for_one,
            # Amounts exceed 2^63, so they travel as strings and are parsed as uint256.
            "amountSpecified": str(self.amount_specified),
            "hookData": self.hook_data,
        }


@dataclass(frozen=True)
class RequoteResult:
    tx_hash: str
    log_index: int
    ok: bool
    expected: int
    error: str


def cache_dir() -> Path:
    d = repo_root() / CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_batch(fills: list[RequoteInput], path: Path) -> None:
    path.write_text(
        json.dumps({"count": len(fills), "fills": [f.to_json() for f in fills]}, indent=2),
        encoding="utf-8",
    )


def run_batch(
    chain: str,
    fills: list[RequoteInput],
    *,
    name: str = "batch",
    timeout: float = 1800.0,
) -> list[RequoteResult]:
    """Re-quote a batch of fills on a fork of `chain`."""
    if not fills:
        return []

    rpc_env = {"base": "BASE_RPC_ARCHIVE", "bnb": "BNB_RPC_ARCHIVE"}.get(
        chain, f"{chain.upper()}_RPC_ARCHIVE"
    )
    url = os.environ.get(rpc_env)
    if not url:
        raise RuntimeError(f"{rpc_env} is not set")

    in_path = cache_dir() / f"{name}-in.json"
    out_path = cache_dir() / f"{name}-out.json"
    write_batch(fills, in_path)
    out_path.unlink(missing_ok=True)

    # Paths are passed relative to contracts/, which is where forge runs and where
    # `fs_permissions` is anchored.
    rel_in = os.path.relpath(in_path, repo_root() / "contracts")
    rel_out = os.path.relpath(out_path, repo_root() / "contracts")

    cmd = [
        "forge",
        "script",
        SCRIPT,
        "--sig",
        "run(string,string,address)",
        rel_in,
        rel_out,
        pool_manager(chain),
        "--fork-url",
        url,
    ]
    proc = subprocess.run(
        cmd,
        cwd=repo_root() / "contracts",
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if not out_path.is_file():
        tail = (proc.stderr or proc.stdout)[-800:]
        raise RuntimeError(f"requote produced no output:\n{tail}")

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    return [
        RequoteResult(
            tx_hash=r["txHash"],
            log_index=int(r["logIndex"]),
            ok=bool(r["ok"]),
            expected=int(r["expected"]),
            error=str(r.get("error", "")),
        )
        for r in raw
    ]


def load_cached_batch(name: str) -> list[RequoteResult]:
    """Read a previously written quote batch.

    Quotes are a pure function of (fill, chain state at that block), so re-running a batch
    produces identical numbers at roughly 30 seconds per fill. Being able to re-aggregate
    from cache is what makes the threshold sensitivity sweep affordable.
    """
    path = cache_dir() / f"{name}-out.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"no cached quote batch at {path}; run without --reuse-quotes first"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        RequoteResult(
            tx_hash=r["txHash"],
            log_index=int(r["logIndex"]),
            ok=bool(r["ok"]),
            expected=int(r["expected"]),
            error=str(r.get("error", "")),
        )
        for r in raw
    ]


def result_key(tx_hash: str, log_index: int) -> tuple[str, int]:
    """The identity of a fill. Used everywhere results are matched back to inputs."""
    return (tx_hash.lower(), int(log_index))


def excess_take_bps(expected: int, realized: int, nominal_fee_pips: int) -> float:
    """`docs/METRICS.md`: take minus the fee the pool advertises, clipped at zero.

    `nominal_fee_pips` is in hundredths of a bip (v4's unit), so 3000 == 0.30% == 30 bps.
    """
    if expected <= 0:
        return 0.0
    shortfall = (expected - realized) / expected
    take_bps = shortfall * 10_000
    nominal_bps = nominal_fee_pips / 100.0
    return max(0.0, take_bps - nominal_bps)
