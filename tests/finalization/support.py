import json
from pathlib import Path

from agent_reliability_lab.agent.demo import call
from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, ExperimentConfig, OracleSpec
from agent_reliability_lab.evaluation.scoring import score

ROOT = Path(__file__).parents[2]
DOC = call("get_document", document_id="policy_001")
WRITE = call("update_task", task_id="task_001", expected_version=1, patch={"status": "resolved"})
ANSWER = {"answer": "support policy"}


def configuration(**updates):
    value = json.loads((ROOT / "benchmarks/evaluation/checkpoint5.json").read_text())
    value.update(transport="memory", experimental_evaluator="1.5.0")
    value.update(updates)
    return ExperimentConfig.model_validate_json(json.dumps(value))


def path_for(sid):
    for directory in (
        "attacks/development",
        "faults/development",
        "controls/development",
        "development",
    ):
        path = ROOT / "benchmarks" / directory / (sid + ".json")
        if path.exists():
            return path
    raise ValueError(sid)


def frozen(trial):
    return Evidence.model_validate_json(json.dumps(trial["evidence"]))


def evaluate(trial, evidence=None, version="1.5.0", experiment=None):
    return score(
        Scenario.model_validate_json(json.dumps(trial["scenario"])),
        OracleSpec.model_validate_json(json.dumps(trial["oracle"])),
        evidence or frozen(trial),
        trial["metadata"],
        experimental_evaluator=version,
        experiment=experiment,
    )
