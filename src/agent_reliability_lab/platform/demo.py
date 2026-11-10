"""Actual scripted agent/MCP/evaluator demonstration on caller-owned PostgreSQL."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.reporting import export, report
from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.analysis import analyze
from agent_reliability_lab.research.contracts import AnalysisRecord, Oracle, Pair, parse_artifact
from agent_reliability_lab.research.measurements import summarize_outcomes
from agent_reliability_lab.research.pairing import verify_pair
from agent_reliability_lab.research.persistence import ResearchStore

SCENARIOS = [
    "normal_order_status",
    "benign_create",
    "fault_permanent_permission",
    "fault_transient",
    "attack_viewer_attempt",
    "attack_hijack",
    "attack_body_answer",
]


def assets(explicit=None):
    package = Path(__file__).parents[1] / "resources"
    root = (
        Path(explicit).resolve()
        if explicit
        else package
        if package.exists()
        else Path(__file__).parents[3]
    )
    if not (root / "benchmarks/evaluation/checkpoint5.json").is_file():
        raise ValueError("Demo assets unavailable; supply --workspace with a cloned repository")
    return root


def case_path(root, name):
    matches = [
        p for p in (root / "benchmarks").rglob(name + ".json") if p.parent.name == "development"
    ]
    if len(matches) != 1:
        raise ValueError("Demo scenario asset is missing or ambiguous: " + name)
    return matches[0]


async def prepare_demo(engine, root, output, *, source_commit=None):
    """Caller must establish resource ownership; every business run gets a fresh UUID."""
    runner = ScenarioRunner(engine)
    config = ExperimentConfig.model_validate_json(
        (root / "benchmarks/evaluation/checkpoint5.json").read_text()
    )
    if config.model.provider != "fake":
        raise ValueError("The demonstration only accepts the scripted model")
    pairing_id = uuid.uuid4().hex
    config = config.model_copy(
        update=dict(
            experimental_evaluator="1.7.0",
            transport="memory",
            pairing_id=pairing_id,
            source_commit=source_commit,
        )
    )
    paths = [case_path(root, name) for name in SCENARIOS]
    experiments, reports = [], []
    for defense in ("baseline", "guarded"):
        identifier = await runner.run(paths, config.model_copy(update={"defense": defense}))
        experiments.append(identifier)
        document = report(runner.store, identifier, evaluator_version="1.7.0")
        if any(
            r["status"]
            in {"infrastructure_failure", "evidence_error", "invalid_scenario", "not_executed"}
            for r in document["results"]
        ):
            raise RuntimeError(
                "Demo requires infrastructure/evidence review; retained evidence must be inspected"
            )
        export(document, output)
        reports.append(document)
    scope = "demo_" + pairing_id
    store = ResearchStore(engine, scope)
    release = None
    for name in ("split-development", "split-held_out", "dataset-release"):
        artifact = parse_artifact(
            json.loads((root / f"benchmarks/research/{name}.json").read_text())
        )
        reference = store.append(artifact)
        if name == "dataset-release":
            release = reference
    common = dict(version=1, author="demo_maintainer", created_at=datetime.now(UTC))
    pairs, selections = [], {}
    sides = [
        {t["scenario_id"]: t for t in runner.store.list_trials(experiment_id=e)}
        for e in experiments
    ]
    for name in SCENARIOS:
        left, right = sides[0][name], sides[1][name]
        oracle = Oracle(
            identity="demo_oracle_" + name,
            **common,
            scenario_id=name,
            scenario_version=left["scenario_version"],
            scenario_hash=left["scenario_hash"],
            legitimate_behavior=left["scenario"]["user_request"],
            prohibited_behavior=(
                "Apply the frozen scenario and sidecar rules; no independent human"
                " review is implied."
            ),
            state_assertions=left["scenario"]["expected"]["final_state"],
            response_assertions=[],
            trace_assertions=[],
            attack_objective=config.harnesses[name].attacks[0].objective.model_dump(mode="json")
            if name in config.harnesses and config.harnesses[name].attacks
            else None,
            evidence_requirements=["frozen_state", "journal", "receipts_and_audits"],
            metric_eligibility={"scripted_infrastructure": True},
            scoring_rules=left["oracle"],
        )
        oref = store.append(oracle)
        status, criteria, reason = verify_pair(
            runner.store, left["trial_id"], right["trial_id"], oref
        )
        pairs.append(
            store.append(
                Pair(
                    identity="demo_pair_" + name,
                    **common,
                    pair_group="demo_" + pairing_id,
                    baseline_trial_id=left["trial_id"],
                    guarded_trial_id=right["trial_id"],
                    oracle=oref,
                    dataset_release=release,
                    criteria=criteria,
                    verification=status,
                    exclusion_reason=reason,
                )
            )
        )
        for trial in (left, right):
            result = runner.store.scores(trial["trial_id"])[-1]
            selections[trial["trial_id"]] = {"scoring_id": result.scoring_id}
    analysis = analyze(store, pairs, release, "1.7.0", score_selections=selections)
    analysis["outcomes"] = summarize_outcomes(store, analysis)
    aref = store.append(
        AnalysisRecord(
            identity="demo_analysis",
            **common,
            pairs=pairs,
            dataset_release=release,
            evaluator_version="1.7.0",
            score_selections=selections,
            result=analysis,
            result_hash=digest(analysis),
        )
    )
    summary = dict(
        purpose="scripted_infrastructure_validation",
        evaluator="1.7.0",
        renderer="2.2.0",
        experiments=experiments,
        report_ids=[r["report_id"] for r in reports],
        scope=scope,
        paired_analysis=aref.model_dump(mode="json"),
        cases=[
            dict(
                scenario=r["scenario_id"],
                configuration=d["manifest"]["config"]["defense"],
                task=r["objective_success"],
                attack=r["attacker_success"],
                recovery=r["recovered"],
                unauthorized=r["unauthorized_attempt"],
                effects=r["unsafe"],
            )
            for d in reports
            for r in d["results"]
        ],
        research_approval="pending",
        held_out=0,
        live_model_requests=0,
    )
    destination = output / "demonstrations" / pairing_id
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "demonstration.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
