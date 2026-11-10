"""Explicit shared synthetic accounting fixtures; not execution evidence."""

import uuid

from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.contracts import Evidence, OracleSpec
from agent_reliability_lab.evaluation.scoring import score
from agent_reliability_lab.opsdesk.fixtures import digest

from .support import ROOT, configuration


def facts(outcome, exposure, index=1, *, resume=False, eligible=True, version="1.5.0"):
    s = Scenario.model_validate_json(
        (ROOT / "benchmarks/development/normal_order_status.json").read_text()
    )
    e = Evidence.model_validate_json(
        (ROOT / "tests/evaluation/data/normal_order_status.json").read_text()
    )
    meta = dict(
        trial_id=uuid.UUID(int=index).hex,
        experiment_id="a" * 32,
        execution_id=e.execution_id,
        scenario_id=s.scenario_id,
        scenario_version=s.scenario_version,
        scenario_hash=digest(s.model_dump(mode="json")),
        category=s.category,
        split="development",
        trial_index=index,
        mode="scripted",
    )
    r = score(s, OracleSpec(), e, meta)
    r.evaluator_version = version
    r.scenario_id = "attack_hijack"
    r.scenario_hash = configuration().harnesses["attack_hijack"].scenario_hash
    r.trial_index = index
    r.eligible = eligible
    r.attack_eligible = exposure is True
    r.attacker_success = outcome
    r.scoring_provenance.update(
        requested_evaluator_version=version, effective_evaluator_version=version
    )
    if resume:
        e.execution.update(
            status="interrupted",
            result={**e.execution["result"], "status": "interrupted", "resume_eligible": True},
        )
    r.agent_status = e.execution["status"]
    goal = dict(
        injection_id="test_attack",
        objective="workflow_hijack",
        exposed=exposure is True,
        success=outcome,
        attribution={
            "status": "verified_unexposed_completed"
            if exposure is False
            else "eligible_match"
            if outcome
            else "indeterminate"
        },
    )
    r.experimental = dict(
        configuration="baseline",
        case_kind="attack",
        objectives=[goal],
        exposures=[dict(injection_id="test_attack", kind="attack", exposed=exposure)],
        verified_attack_exposure=exposure,
    )
    capture = e.model_dump(mode="json")
    t = dict(
        trial_id=r.trial_id,
        scenario_id=r.scenario_id,
        trial_index=index,
        evidence=capture,
        evidence_hash=digest(capture),
        cleanup={"status": "synthetic_unit_fixture"},
    )
    return t, r


class Store:
    def __init__(self, pairs, repeats=1, version="1.5.0", empty=False):
        cfg = configuration(repeats=repeats, experimental_evaluator=version)
        self.trials = [p[0] for p in pairs]
        self.results = {p[0]["trial_id"]: [p[1]] for p in pairs}
        manifest = dict(
            config=cfg.model_dump(mode="json"),
            cases=[]
            if empty
            else [
                dict(
                    scenario_id="attack_hijack",
                    scenario_hash=cfg.harnesses["attack_hijack"].scenario_hash,
                )
            ],
            purpose="scripted_infrastructure_validation",
        )
        self.record = dict(
            experiment_id="a" * 32, manifest=manifest, manifest_hash=digest(manifest)
        )

    def experiment(self, _):
        return self.record

    def list_trials(self, **kwargs):
        return self.trials

    def scores(self, identifier):
        return self.results[identifier]

    def save_report(self, *args):
        return "b" * 32
