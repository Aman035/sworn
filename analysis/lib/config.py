"""Load and validate `analysis/config.yaml`.

Pipelines must read every threshold from here. A number hard-coded in a pipeline is a
bug: `docs/METRICS.md` and this file are the only places a parameter is defined.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    """Repo root, resolved from this file rather than the cwd so pipelines are cwd-agnostic."""
    return Path(__file__).resolve().parents[2]


def config_path() -> Path:
    return repo_root() / "analysis" / "config.yaml"


@dataclass(frozen=True)
class Chain:
    name: str
    chain_id: int
    rpc_env: str
    priority: int

    def rpc_url(self) -> str:
        url = os.environ.get(self.rpc_env)
        if not url:
            raise RuntimeError(
                f"{self.rpc_env} is not set; archive RPC required for chain {self.name}"
            )
        return url


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with config_path().open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ValueError("config.yaml must parse to a mapping")
    return cfg


def chains() -> dict[str, Chain]:
    raw = load_config()["chains"]
    return {
        name: Chain(
            name=name,
            chain_id=int(c["chain_id"]),
            rpc_env=str(c["rpc_env"]),
            priority=int(c["priority"]),
        )
        for name, c in raw.items()
    }


def chain(name: str) -> Chain:
    try:
        return chains()[name]
    except KeyError as exc:
        raise KeyError(f"unknown chain {name!r}; known: {sorted(chains())}") from exc


def path_for(key: str) -> Path:
    """Resolve a repo-relative path from the `paths` section to an absolute path."""
    return repo_root() / load_config()["paths"][key]
