import json

from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, OracleSpec
from agent_reliability_lab.evaluation.scoring import score


def frozen(trial):
    return Evidence.model_validate_json(json.dumps(trial["evidence"]))


def evaluate(trial, evidence=None, version="1.6.0", experiment=None):
    return score(
        Scenario.model_validate_json(json.dumps(trial["scenario"])),
        OracleSpec.model_validate_json(json.dumps(trial["oracle"])),
        evidence or frozen(trial),
        trial["metadata"],
        experimental_evaluator=version,
        experiment=experiment,
    )


def prefix_before_validation(evidence, turn=1):
    e = evidence.model_copy(deep=True)
    request = next(r for r in e.requests if r["turn"] == turn)
    cut = next(
        v["sequence"]
        for v in e.events
        if v["event_type"] == "model_response"
        and v["payload"]["request_id"] == request["request_id"]
    )
    e.events = [v for v in e.events if v["sequence"] <= cut]
    high = next(
        r["sequence"]
        for r in e.provenance
        if r["kind"] == "journal_event" and r["body"]["sequence"] == cut
    )
    e.provenance = e.provenance[:high]
    e.operations = [o for o in e.operations if o["turn"] < turn]
    ids = {o["proposal_id"] for o in e.operations}
    e.attempts = [a for a in e.attempts if a["proposal_id"] in ids]
    e.requests = [r for r in e.requests if r["turn"] <= turn]
    e.execution.update(
        status="running",
        result=None,
        journal_seq=cut,
        tool_calls=len(e.attempts),
        llm_calls=len(e.requests),
    )
    return e


def reseal(evidence):
    from agent_reliability_lab.agent.provenance import seal

    records = []
    for r in evidence.provenance:
        records.append(
            seal(
                evidence.execution_id,
                len(records) + 1,
                r["kind"],
                r["reference"],
                r["body"],
                records[-1]["record_hash"] if records else None,
            )
        )
    evidence.provenance = records


def configuration(**updates):
    from tests.finalization.support import configuration as historical_configuration

    return historical_configuration(experimental_evaluator="1.6.0", **updates)
