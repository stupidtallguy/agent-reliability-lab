import json

import pytest

from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation.capture_v170 import score_capture
from agent_reliability_lab.evaluation.contracts import Evidence, OracleSpec
from agent_reliability_lab.evaluation.reporting import report, reproduce
from agent_reliability_lab.opsdesk.fixtures import digest
from tests.remediation16.support import evaluate, prefix_before_validation

from .support import configuration

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_original_proposal_before_validation_is_still_scored(lab):
    trial, result = await lab[1]("attack_viewer_attempt")
    assert result.attacker_success is True
    evidence = Evidence.model_validate_json(json.dumps(trial["evidence"]))
    prefix = prefix_before_validation(evidence)
    assert all(o["turn"] != 1 for o in prefix.operations)
    scored = evaluate(trial, prefix, version="1.7.0")
    assert scored.attacker_success is True, scored.model_dump_json()


async def test_frozen_append_only_rescore_and_renderer_reproduction(lab):
    runner, run = lab
    trial, original = await run()
    before = digest(trial["evidence"])
    pinned = report(runner.store, trial["experiment_id"], evaluator_version="1.7.0")
    revised = runner.rescore(trial["trial_id"], experimental_evaluator="1.7.0")
    assert revised.scoring_id != original.scoring_id
    assert revised.attacker_success == original.attacker_success
    assert len(runner.store.scores(trial["trial_id"])) == 2
    assert digest(runner.store.trial(trial["trial_id"])["evidence"]) == before
    assert reproduce(runner.store, pinned["report_id"]) == pinned


async def test_malformed_raw_capture_retains_requested_version_and_frozen_plan(lab):
    runner, run = lab
    trial, _ = await run()
    capture = dict(trial["evidence"], execution=[])
    result = score_capture(
        Scenario.model_validate_json(json.dumps(trial["scenario"])),
        OracleSpec.model_validate_json(json.dumps(trial["oracle"])),
        capture,
        trial["metadata"],
        runner.store.experiment(trial["experiment_id"]),
    )
    assert result.status == "evidence_error" and result.evaluator_version == "1.7.0"
    assert result.scoring_provenance["effective_evaluator_version"] is None
    assert result.experimental["planned_trial"]["attack_count"] == 1
    assert result.evidence_hash == digest(capture)


async def test_stdio_real_mcp_has_same_candidate_provenance(lab):
    _, result = await lab[1](config=configuration(transport="stdio"))
    assert result.attacker_success is True, result.model_dump_json()
    assert result.evaluator_version == "1.7.0"
