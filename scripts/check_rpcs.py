"""Preflight every configured RPC endpoint before a long pipeline run.

Sworn needs archive state and `debug_traceCall`, not merely a responsive node. Finding
that out ninety minutes into a Phase 3 run is expensive, so this runs first.

    .venv/bin/python scripts/check_rpcs.py            # every configured chain
    .venv/bin/python scripts/check_rpcs.py base bnb   # just these
    .venv/bin/python scripts/check_rpcs.py --required base,bnb

Exit code is 0 when every *required* chain is fully capable. Optional chains that are
unset or degraded are reported and do not fail the run, because Base and BNB alone are
enough for the headline numbers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))

from dotenv import load_dotenv  # noqa: E402

from lib.config import chains  # noqa: E402
from lib.rpc import EndpointReport, check_endpoint  # noqa: E402

DEFAULT_REQUIRED = ("base", "bnb")


def render(report: EndpointReport) -> None:
    mark = "ok  " if report.ok else "FAIL"
    print(f"  {mark} {report.chain:<9} {report.url_redacted}")

    if not report.reachable:
        print(f"         unreachable: {report.error or 'unknown error'}")
        return

    if not report.chain_id_matches:
        print(
            f"         chain id mismatch: got {report.chain_id}, expected {report.expected_chain_id}"
        )

    print(f"         chain id {report.chain_id}, latest block {report.latest_block:,}")
    for cap in report.capabilities:
        flag = "ok " if cap.ok else "no "
        print(f"         [{flag}] {cap.name}: {cap.detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "chains", nargs="*", help="chains to check (default: all configured)"
    )
    parser.add_argument(
        "--required",
        default=",".join(DEFAULT_REQUIRED),
        help="comma-separated chains that must be fully capable for exit 0",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    known = chains()
    selected = args.chains or list(known)
    unknown = [c for c in selected if c not in known]
    if unknown:
        print(f"unknown chain(s): {unknown}; known: {sorted(known)}", file=sys.stderr)
        return 2

    required = {c.strip() for c in args.required.split(",") if c.strip()}

    print(
        f"checking {len(selected)} endpoint(s); required: {sorted(required) or 'none'}\n"
    )
    reports = []
    for name in selected:
        report = check_endpoint(known[name], timeout=args.timeout)
        reports.append(report)
        render(report)
        print()

    failures = [r for r in reports if r.chain in required and not r.ok]
    degraded = [r for r in reports if r.chain not in required and not r.ok]

    if degraded:
        print("optional chains not fully capable (pipelines will skip them):")
        for r in degraded:
            reason = r.error or f"missing {r.missing()}"
            print(f"  - {r.chain}: {reason}")
        print()

    if failures:
        print("REQUIRED chains not usable:", file=sys.stderr)
        for r in failures:
            reason = r.error or f"missing {r.missing()}"
            print(f"  - {r.chain}: {reason}", file=sys.stderr)
        return 1

    print("all required endpoints have archive state, log range and debug_traceCall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
