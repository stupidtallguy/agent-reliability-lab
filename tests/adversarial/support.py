"""Shared scenario loading without importing a pytest conftest module."""

import json
from pathlib import Path

from agent_reliability_lab.evaluation.contracts import ExperimentConfig

ROOT = Path(__file__).parents[2]


def configuration(**updates):
    payload = json.loads((ROOT / "benchmarks/evaluation/checkpoint5.json").read_text())
    payload.update({"transport": "memory", **updates})
    return ExperimentConfig.model_validate_json(json.dumps(payload))


def path_for(sid):
    for category in ("faults", "attacks", "controls"):
        path = ROOT / f"benchmarks/{category}/development/{sid}.json"
        if path.exists():
            return path
    return ROOT / f"benchmarks/development/{sid}.json"
