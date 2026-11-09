import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from agent_reliability_lab.evaluation import tables as t
from agent_reliability_lab.evaluation.reporting import report, reproduce
from agent_reliability_lab.evaluation.selection import IncompatibleCohort

from .support import configuration

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_report_manifests_pin_revisions_and_reproduce_frozen_content(lab):
    runner, run = lab
    identifier, [(trial, _)] = await run(["attack_body_answer"], configuration())
    first = report(runner.store, identifier)
    old_hash = trial["evidence_hash"]
    runner.rescore(trial["trial_id"])
    second = report(runner.store, identifier)
    replay = reproduce(runner.store, first["report_id"])
    assert first == replay
    assert first["report_manifest"]["selected_scores"][0]["revision"] == 1
    assert second["report_manifest"]["selected_scores"][0]["revision"] == 2
    assert first["report_manifest"]["content_hash"] != second["report_manifest"]["content_hash"]
    assert runner.store.trial(trial["trial_id"])["evidence_hash"] == old_hash
    again = report(runner.store, identifier, scoring_ids=[first["results"][0]["scoring_id"]])
    assert again["report_manifest"]["content_hash"] == first["report_manifest"]["content_hash"]
    assert again["report_id"] != first["report_id"]
    with pytest.raises(DBAPIError), runner.engine.begin() as c:
        c.execute(
            t.report_manifests.update()
            .where(t.report_manifests.c.report_id == first["report_id"])
            .values(content_hash="0" * 64)
        )
    assert (
        reproduce(runner.store, first["report_id"])["report_manifest"] == first["report_manifest"]
    )


async def test_explicit_historical_revision_and_mixed_cohort_rejection(lab):
    runner, run = lab
    identifier, pairs = await run(["attack_body_answer", "attack_hijack"], configuration())
    runner.rescore(pairs[0][0]["trial_id"], experimental_evaluator="1.1.0")
    with pytest.raises(IncompatibleCohort):
        report(runner.store, identifier)
    current = report(runner.store, identifier, evaluator_version="1.5.0")
    historic = report(runner.store, identifier, evaluator_version="1.1.0")
    assert len(current["results"]) == 2 and len(historic["results"]) == 1
    assert historic["selection"]["evaluator_version"] == "1.1.0"
    assert "population" not in historic["summary"]["security"]
    assert historic["selection"]["unavailable"]
    with runner.engine.connect() as c:
        assert (
            c.execute(
                sa.select(sa.func.count())
                .select_from(t.report_manifests)
                .where(t.report_manifests.c.report_id == current["report_id"])
            ).scalar_one()
            == 1
        )
