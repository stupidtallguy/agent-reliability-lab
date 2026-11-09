import uuid

import pytest

from agent_reliability_lab.adversarial.reporting import compare
from agent_reliability_lab.evaluation.reporting import report

from .support import configuration

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_paired_security_uses_the_same_verified_population_as_reports(lab):
    runner, run = lab
    config = configuration(pairing_id=uuid.uuid4().hex)
    baseline, _ = await run(["attack_body_answer"], config)
    guarded, _ = await run(["attack_body_answer"], config.model_copy(update={"defense": "guarded"}))
    compared = compare(runner.store, baseline, guarded)
    for name, experiment_id in (("baseline", baseline), ("guarded", guarded)):
        paired = compared[name + "_security"]["attack_outcome_coverage"]
        individual = report(runner.store, experiment_id)["summary"]["security"][
            "attack_outcome_coverage"
        ]
        assert paired == individual
        assert paired["configured_attack_trials"] == 1
        assert paired["trial_metadata_unavailable"] == 0


async def test_report_label_exception_does_not_allow_credential_fields(lab):
    runner, run = lab
    experiment_id, [(trial, result)] = await run(["attack_body_answer"])
    document = report(runner.store, experiment_id)
    summary = {**document["summary"], "api_key": "synthetic-unrecognized-secret"}
    with pytest.raises(ValueError, match="sensitive report"):
        runner.store.save_report_bundle(
            experiment_id, [result], summary, document["report_manifest"]
        )
    assert runner.store.trial(trial["trial_id"])["evidence_hash"] == trial["evidence_hash"]
