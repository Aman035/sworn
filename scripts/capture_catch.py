"""Run the mainnet catch and record it as a result file.

The README prints what `ProtectedSwap.fork.t.sol` observed. Under this repo's own rule a
number has to come from `data/results`, not from a paragraph someone typed, so the test is
run here and its output parsed into `caught.json` with the block and addresses it came
from. Re-running this is the only way those figures change.

    python scripts/capture_catch.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from sworn_analysis.lib.config import load_config  # noqa: E402
from sworn_analysis.lib.snapshot import script_commit  # noqa: E402

TEST = "test/fork/ProtectedSwap.fork.t.sol"
OUT = ROOT / "data" / "results" / "caught.json"

# Constants the test pins, restated here so the result file is self-describing.
BLOCK = 51_247_545
TX = "0x528ff79b489621493d779401eed2d60465f8b23f375655e73fef0c41504cc525"
HOOK = "0xf54473f4c554baa8411c0a7dac7df735f34d00c4"
POOL_TOKEN = "0x5ab000ff9b9ffe0349ce5ffa5fd86f217c3680f5"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def number_after(text: str, label: str) -> int:
    m = re.search(re.escape(label) + r"\s+(\d+)", text)
    if not m:
        raise SystemExit(f"could not find {label!r} in the test output")
    return int(m.group(1))


def main() -> int:
    env = dict(os.environ)
    if not env.get("BASE_RPC_ARCHIVE"):
        raise SystemExit("BASE_RPC_ARCHIVE is not set; the fork test cannot run")

    proc = subprocess.run(
        ["forge", "test", "--match-path", TEST, "-vv"],
        cwd=ROOT / "contracts",
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout[-3000:])
        raise SystemExit("the fork test failed; nothing recorded")

    out = proc.stdout
    naive = number_after(out, "caller A (NaiveRouter) receives")
    probed = number_after(out, "caller B (SwornRouter) receives")
    settled = number_after(out, "what Sworn settled for")

    # The catch is an on-chain observation, not a derivation from a dataset. Its
    # provenance is the fills snapshot that pointed at this hook and block in the first
    # place, plus the block itself, which is recorded under `where`.
    divergence = json.loads((ROOT / "data/results/divergence.json").read_text())

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "capture_catch",
            "snapshots": divergence["meta"]["snapshots"],
        },
        "where": {
            "chain": "base",
            "block": BLOCK,
            "original_tx": TX,
            "hook": HOOK,
            "test": f"contracts/{TEST}",
            "pool": {"currency0": POOL_TOKEN, "currency1": USDC},
        },
        "observed": {
            # Identical swap, identical block, two callers.
            "caller_a_out": naive,
            "caller_b_out": probed,
            "charged_extra_bps": round((naive - probed) * 10_000 / naive),
            # What Sworn did about it.
            "sworn_settled_out": settled,
            "recovered_bps": round((settled - probed) * 10_000 / probed),
        },
    }
    OUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    o = document["observed"]
    print(f"  caller A {o['caller_a_out']:,}   caller B {o['caller_b_out']:,}")
    print(
        f"  charged extra {o['charged_extra_bps']} bps, Sworn recovered {o['recovered_bps']} bps"
    )
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
