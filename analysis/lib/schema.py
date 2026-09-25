"""Result-file schema access and validation.

`analysis/schemas/results.schema.json` is the contract between the pipelines, the
README linter, the dashboard and the attestor. Everything that reads or writes
`data/results/*.json` goes through here so there is one definition of "valid".
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .config import load_config, repo_root


def schema_path() -> Path:
    return repo_root() / load_config()["paths"]["schema"]


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    with schema_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


def result_files() -> dict[str, str]:
    """Map `census.json` -> `#/$defs/census`."""
    return dict(load_schema()["x-files"])


def definition_for(filename: str) -> dict[str, Any]:
    """The subschema a given result file must validate against."""
    files = result_files()
    if filename not in files:
        raise KeyError(f"{filename} is not a declared result file; known: {sorted(files)}")
    return {"$ref": files[filename], "$defs": load_schema()["$defs"]}


def validator_for(filename: str) -> Draft202012Validator:
    return Draft202012Validator(definition_for(filename))


def validate_result(filename: str, document: Any) -> None:
    """Raise with every error at once, so a pipeline run reports all problems in one go."""
    errors = sorted(validator_for(filename).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        lines = [f"{filename} failed schema validation ({len(errors)} error(s)):"]
        lines += [
            f"  at {'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors
        ]
        raise ValueError("\n".join(lines))


def resolve_field(path: str) -> dict[str, Any]:
    """Resolve a docs-style field path such as `divergence.hooks[].charged_rate`.

    The first segment names a definition; `[]` steps into array items. Raises KeyError
    with the available keys when a segment does not exist, which is what makes the
    Phase 1 docs linter useful rather than merely red.
    """
    schema = load_schema()
    segments = path.split(".")
    root = segments[0].removesuffix("[]")
    try:
        node: dict[str, Any] = schema["$defs"][root]
    except KeyError as exc:
        raise KeyError(f"unknown result definition {root!r} in path {path!r}") from exc

    def step_items(n: dict[str, Any], where: str) -> dict[str, Any]:
        if "items" not in n:
            raise KeyError(f"{where} is not an array in path {path!r}")
        return n["items"]

    if segments[0].endswith("[]"):
        node = step_items(node, segments[0])

    for seg in segments[1:]:
        key = seg.removesuffix("[]")
        props = node.get("properties")
        if not props or key not in props:
            available = sorted(props) if props else []
            raise KeyError(f"{path!r}: no field {key!r}; available: {available}")
        node = props[key]
        if seg.endswith("[]"):
            node = step_items(node, seg)
    return node
