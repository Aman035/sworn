"""Fallback GitHub Actions validator for when `actionlint` is not installed.

It is deliberately shallow: parse each workflow, require the keys that a broken
workflow most often loses (name/on/jobs, a `runs-on` and at least one step per job),
and reject a step that has neither `uses` nor `run`. `actionlint` in CI does the
real checking; this keeps the local Phase 0 gate honest without a Go toolchain.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path.name}: invalid YAML: {exc}"]

    if not isinstance(doc, dict):
        return [f"{path.name}: workflow must be a mapping"]

    # PyYAML parses the bare key `on` as the boolean True (YAML 1.1 truthiness).
    trigger = doc.get("on", doc.get(True))
    if trigger is None:
        errors.append(f"{path.name}: missing 'on' trigger")
    if not doc.get("name"):
        errors.append(f"{path.name}: missing 'name'")

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return errors + [f"{path.name}: missing 'jobs'"]

    for job_name, job in jobs.items():
        where = f"{path.name}:{job_name}"
        if not isinstance(job, dict):
            errors.append(f"{where}: job must be a mapping")
            continue
        if "uses" in job:  # reusable workflow call, no steps of its own
            continue
        if not job.get("runs-on"):
            errors.append(f"{where}: missing 'runs-on'")
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"{where}: missing 'steps'")
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                errors.append(f"{where}: step {i} must be a mapping")
            elif "uses" not in step and "run" not in step:
                errors.append(f"{where}: step {i} has neither 'uses' nor 'run'")
    return errors


def main() -> int:
    if not WORKFLOW_DIR.is_dir():
        print(f"no workflow directory at {WORKFLOW_DIR}", file=sys.stderr)
        return 1
    files = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))
    if not files:
        print("no workflows found", file=sys.stderr)
        return 1

    all_errors = [e for f in files for e in validate(f)]
    for err in all_errors:
        print(err, file=sys.stderr)
    if all_errors:
        return 1
    print(f"validated {len(files)} workflow(s): {', '.join(f.name for f in files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
