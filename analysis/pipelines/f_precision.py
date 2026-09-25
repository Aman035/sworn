"""Pipeline F — how well each detection method predicts measured behaviour.

Ground truth is Phase 3's `divergent` label, which comes from settled trades: what the
hook actually did to users. Each detection method is scored against it.

The expected shape, and the reason this table is in the README rather than a single
headline number:

* **static** — high recall, terrible precision. 99.2% of Base hooks contain an
  environment opcode, so a detector built on presence flags nearly everything.
* **differential** — catches hooks that price differently by environment, misses
  dice-rollers and anything keyed on state.
* **trace** — catches hooks that *execute* an environment read while pricing. Needs
  `debug_traceCall`, which not every provider offers.
* **settled_trade** — catches everything, but only after someone has been hurt.

That last row is the argument for `SwornRouter`: every detector is either imprecise or
retrospective, and neither is a guarantee.

    python -m sworn_analysis.pipelines.f_precision --chain base
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..lib.config import load_config, path_for, repo_root
from ..lib.schema import validate_result
from ..lib.snapshot import script_commit, snapshot_ref

GROUND_TRUTH = "phase-3 divergent (settled trades)"


def _load(name: str) -> dict[str, Any] | None:
    path = path_for("results") / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def confusion(predicted: set[str], actual: set[str], universe: set[str]) -> dict[str, int]:
    tp = len(predicted & actual)
    fp = len(predicted - actual)
    fn = len(actual - predicted)
    tn = len(universe - predicted - actual)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def rates(c: dict[str, int]) -> dict[str, float]:
    precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
    recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def build(chain: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    probe = _load("probe.json")
    divergence = _load("divergence.json")
    if probe is None:
        raise SystemExit("no probe.json; run f_probe first")
    if divergence is None:
        raise SystemExit(
            "no divergence.json; run b_divergence first — there is no ground truth without it"
        )

    probed = {h["address"].lower(): h for h in probe["hooks"] if h["chain"] == chain}
    measured = {h["address"].lower(): h for h in divergence["hooks"] if h["chain"] == chain}

    # Only hooks that were both probed and measured can be scored. Reporting the overlap
    # matters: a matrix over a handful of hooks says very little.
    universe = set(probed) & set(measured)
    if not universe:
        raise SystemExit(
            f"no hooks were both probed and measured on {chain}; "
            f"probed {len(probed)}, measured {len(measured)}"
        )

    actual = {a for a in universe if measured[a].get("divergent")}

    methods: dict[str, set[str]] = {
        "static": {a for a in universe if probed[a]["static"]["env_opcodes_present"]},
        "dynamic": {
            a for a in universe if "differential-disagreement" in probed[a].get("signals", [])
        },
        "trace": {
            a for a in universe if probed[a].get("trace", {}).get("env_opcodes_on_swap_path")
        },
    }
    methods["union"] = methods["static"] | methods["dynamic"] | methods["trace"]
    # Settled trades are the ground truth, so scoring them against themselves is perfect
    # by construction. It is in the table to make the trade-off explicit: the only method
    # that catches everything is the one that runs after the fact.
    methods["settled_trade"] = set(actual)

    rows: list[dict[str, Any]] = []
    for name, predicted in methods.items():
        c = confusion(predicted, actual, universe)
        r = rates(c)
        note = ""
        if name == "settled_trade":
            note = "ground truth; perfect by construction, and only available after a user was hurt"
        elif name == "trace" and not any(
            h.get("trace", {}).get("available") for h in probed.values()
        ):
            note = "debug_traceCall unavailable on this endpoint"
        rows.append({"method": name, **c, **r, **({"notes": note} if note else {})})

    summary = [
        {
            "hooks_scored": len(universe),
            "divergent": len(actual),
            "probed_only": len(set(probed) - universe),
            "measured_only": len(set(measured) - universe),
        }
    ]
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", default="base")
    args = parser.parse_args(argv)

    load_dotenv(repo_root() / ".env")
    methods, summary = build(args.chain)

    document = {
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": int(load_config()["version"]),
            "pipeline": "f_precision",
            "snapshots": [
                snapshot_ref(f"census-{args.chain}"),
                snapshot_ref(f"fills-{args.chain}"),
            ],
        },
        "ground_truth": GROUND_TRUTH,
        "methods": methods,
    }
    validate_result("precision.json", document)

    out: Path = path_for("results") / "precision.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    s = summary[0]
    print(f"  hooks scored (probed AND measured)  {s['hooks_scored']}")
    print(f"  divergent among them                {s['divergent']}")
    print("\n  method          tp  fp  fn  tn   precision  recall")
    for m in methods:
        print(
            f"  {m['method']:<14} {m['tp']:>3} {m['fp']:>3} {m['fn']:>3} {m['tn']:>3}"
            f"     {m['precision']:>6.2f}  {m['recall']:>6.2f}"
        )
    print(f"\nwrote {out.relative_to(repo_root())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
