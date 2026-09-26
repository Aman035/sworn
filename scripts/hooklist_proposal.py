"""Generate the hooklist schema proposal and a worked sample from real measurements.

The hooklist describes hooks by **identity** — who deployed it, is the source verified, is
there an audit — and by **static permissions** decoded from the address. Neither answers
the question an integrator is actually asking, which is *what does this hook do to my
users*. An address-keyed allowlist also cannot express that a listed hook was upgraded the
block after it was listed, and on Base most hooks sit behind a proxy.

This emits:

* `docs/HOOKLIST_PROPOSAL.md` — the proposed fields, with the reasoning and the failure
  each one prevents;
* `data/results/hooklist_proposal.json` — the same fields filled in for every hook this
  repo has actually measured, so the PR arrives with data rather than with a schema.

Every value comes from `data/results/*.json`; nothing here is hand-entered.

    python scripts/hooklist_proposal.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_FOR_IMPORT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_FOR_IMPORT / "analysis"))

from sworn_analysis.lib.snapshot import script_commit  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "results"
PROPOSAL_DOC = ROOT / "docs" / "HOOKLIST_PROPOSAL.md"
PROPOSAL_JSON = RESULTS / "hooklist_proposal.json"

FIELDS: list[tuple[str, str, str]] = [
    (
        "divergenceScore",
        "integer or null",
        "0 (clean) to 100 (avoid), or null when too few fills have been measured to say. "
        "Null rather than 0, so an unmeasured hook can never be mistaken for a clean one.",
    ),
    (
        "divergenceAsOfBlock",
        "integer",
        "The block the measurement describes. A score with no block is a score with no "
        "shelf life, and hooks change.",
    ),
    (
        "divergenceSnapshot",
        "string",
        "sha256 of the dataset the score was computed from, so a reader can re-derive the "
        "number instead of trusting it.",
    ),
    (
        "envSensitive",
        "boolean",
        "The hook executes an environment read (`GASPRICE`, `ORIGIN`, `COINBASE`, "
        "`NUMBER`, `PREVRANDAO`) on the swap path. Attributed by call-stack, so a read "
        "made by a library the hook calls still counts and a read made elsewhere does not.",
    ),
    (
        "intermittent",
        "boolean",
        "The hook's charged rate crosses the threshold in some hours and not others. A "
        "one-shot review of an intermittent hook is a coin flip.",
    ),
    (
        "upgradeable",
        "boolean",
        "Already partly implied by `deployer`, but stated directly: today's bytecode is "
        "not tomorrow's, and listing is permanent while code is not.",
    ),
]


def load(name: str) -> Any:
    path = RESULTS / name
    if not path.is_file():
        raise SystemExit(f"{name} missing — run its pipeline first")
    return json.loads(path.read_text(encoding="utf-8"))


def build_entries() -> list[dict[str, Any]]:
    scores = load("scores.json")
    probe = {h["address"]: h for h in load("probe.json").get("hooks", [])}
    inter = {h["address"]: h for h in load("intermittency.json").get("hooks", [])}

    out: list[dict[str, Any]] = []
    for hook in scores["hooks"]:
        if hook.get("score") is None:
            continue
        address = hook["address"]
        p = probe.get(address, {})
        i = inter.get(address, {})
        out.append(
            {
                "address": address,
                "chain": hook["chain"],
                "divergenceScore": hook["score"],
                "divergenceAsOfBlock": hook["as_of_block"],
                "divergenceSnapshot": f"0x{scores['meta']['snapshots'][0]['sha256']}",
                "envSensitive": bool(p.get("env_sensitive", False)),
                "intermittent": bool(i.get("intermittent", False)),
                # `upgradeable` is an input to the score, not one of its output flags.
                "upgradeable": bool(hook.get("inputs", {}).get("upgradeable", False)),
            }
        )
    return sorted(out, key=lambda e: -e["divergenceScore"])


def write_doc(entries: list[dict[str, Any]]) -> None:
    scored = len(entries)
    env = sum(1 for e in entries if e["envSensitive"])
    upgradeable = sum(1 for e in entries if e["upgradeable"])
    worst = entries[0] if entries else None

    # The proxy argument is about the whole population, not the measured subset: the
    # measured hooks are the busiest ones, and none of them happens to be upgradeable.
    census = load("census.json")
    base = next(c for c in census["chains"] if c["chain"] == "base")
    proxied, hooks_total = int(base["upgradeable"]), int(base["hooks_total"])

    rows = "\n".join(f"| `{name}` | `{kind}` | {why} |" for name, kind, why in FIELDS)
    sample = json.dumps(entries[:3], indent=2) if entries else "[]"

    body = f"""# Hooklist: carry behaviour, not only identity

A proposal for [Uniswap/hooklist](https://github.com/Uniswap/hooklist), with data.

## The gap

The hooklist describes a hook by **who made it** — deployer, verified source, audit link —
and by the **static permissions** encoded in its address. Both are checkable and both are
useful. Neither answers the question an integrator turning on hooks-inclusive routing is
actually asking: *what does this hook do to my users?*

Two specific failures follow:

1. **Listing is permanent; bytecode is not.** {proxied:,} of the {hooks_total:,} hooks on
   Base sit behind a proxy. An address-keyed allowlist cannot express that a listed hook
   changed after it was listed. Of the {scored} hooks measured here, {upgradeable} are
   upgradeable — a fact about which hooks carry the most volume, not a reason to drop the
   field.
2. **Permissions are capability, not behaviour.** `beforeSwapReturnsDelta` says a hook
   *can* alter the amounts. Almost every interesting hook has it. It says nothing about
   whether the hook charges more than it quoted.

## Proposed fields

Added under `properties`, all optional, all absent-means-unknown:

| Field | Type | Why |
| ----- | ---- | --- |
{rows}

The critical convention is that **absence and zero are different**. `divergenceScore: null`
means nobody has measured this hook; `divergenceScore: 0` means somebody measured it and
found nothing. A schema that cannot tell those apart turns "unreviewed" into "safe", which
is the failure mode an allowlist is supposed to prevent.

## Worked sample

`data/results/hooklist_proposal.json` carries these fields for every hook this repo has
measured: {scored} hooks on Base, with {env} executing an environment read on the swap
path{"" if worst is None else f". The highest score is {worst['divergenceScore']}, at `{worst['address']}`"}.

```json
{sample}
```

## Where the values come from

| Field | Source |
| ----- | ------ |
| `divergenceScore` | `data/results/scores.json`, specified in [SCORING.md](SCORING.md) |
| `divergenceAsOfBlock` | the block of the fills snapshot the score was computed over |
| `divergenceSnapshot` | sha256 of that snapshot, recorded in the result's `meta` |
| `envSensitive` | `data/results/probe.json`, `debug_traceCall` with call-stack attribution |
| `intermittent` | `data/results/intermittency.json`, hourly charged rate over 30 days |
| `upgradeable` | `data/results/census.json`, proxy detection from bytecode |

The same values are published on-chain by [`HookBook`](../contracts/src/HookBook.sol), so a
generator can fill this section of the hooklist from a contract call rather than from a
file anyone can edit — and `HookBook` already refuses to report an unmeasured hook as
clean, returning `hasScore() == false` and `INSUFFICIENT_DATA` instead of a zero.

## What this proposal does not claim

- **These scores are not authoritative.** They come from one team's measurement over a
  30-day window on one chain. The point of `divergenceSnapshot` is that you do not have to
  take them on trust.
- **A score is not a guarantee.** It describes what a hook did, not what it will do next
  block. That is why this repo's actual answer is a router that verifies in-transaction;
  the score only hints at which candidates are worth probing.
- **The measurement has a floor.** Roughly half the charged fills in the underlying sample
  are measurement error, quantified and published in `divergence.noise_floor`.
"""
    PROPOSAL_DOC.write_text(body, encoding="utf-8")


def main() -> int:
    entries = build_entries()
    if not entries:
        print("no scored hooks yet — run the scoring pipeline first", file=sys.stderr)
        return 1

    scores_meta = load("scores.json")["meta"]
    document = {
        # Carries provenance like every other result file: this is a claim about mainnet
        # hooks, and a claim with no snapshot behind it is the thing this repo refuses to
        # publish. The gate sweeps `data/results/` and would reject a bare list.
        "meta": {
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "script_commit": script_commit(),
            "config_version": scores_meta["config_version"],
            "pipeline": "hooklist_proposal",
            "snapshots": scores_meta["snapshots"],
        },
        "fields": [{"name": n, "type": t, "why": w} for n, t, w in FIELDS],
        "hooks": entries,
    }
    PROPOSAL_JSON.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    write_doc(entries)
    print(
        f"  {len(entries)} measured hooks written to {PROPOSAL_JSON.relative_to(ROOT)}"
    )
    print(f"  proposal written to {PROPOSAL_DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
