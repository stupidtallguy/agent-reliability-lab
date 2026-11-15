import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from agent_reliability_lab.evaluation.downloads import render_files
from agent_reliability_lab.platform.demo import assets, prepare_demo
from agent_reliability_lab.research.views import ResearchView

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_complete_demo_is_repeatable_and_readonly_views_cannot_write(lab, tmp_path):
    runner = lab[0]
    first = await prepare_demo(runner.engine, assets(), tmp_path)
    second = await prepare_demo(runner.engine, assets(), tmp_path)
    assert first["cases"] == second["cases"]
    assert first["experiments"] != second["experiments"]
    view = ResearchView(runner.engine)
    inventory = view.experiment_inventory()
    selected = {row["experiment_id"]: row for row in inventory}
    assert all(selected[eid]["trial_count"] == 7 for eid in first["experiments"])
    assert all(selected[eid]["demonstration"] is True for eid in first["experiments"])
    for experiment_id, report_id in zip(first["experiments"], first["report_ids"], strict=True):
        record = next(r for r in view.report_index(experiment_id) if r["report_id"] == report_id)
        assert record["evaluator"] == "1.7.0" and record["renderer"] == "2.2.0"
        target = tmp_path / experiment_id / report_id
        assert all(
            (target / name).read_bytes() == data
            for name, data in render_files(view.report(report_id)).items()
        )
    for report_id in first["report_ids"]:
        assert view.report(report_id)["renderer_version"] == "2.2.0"
    readiness = view.readiness(first["scope"])
    assert readiness["human_declared_attestations"] == readiness["held_out_count"] == 0
    assert view.rows("artifacts", identifier=first["scope"], kind="analysis")
    before = view.counts()
    with pytest.raises(DBAPIError) as caught, view.engine.begin() as c:
        c.execute(sa.text("DELETE FROM opsdesk_evaluation.experiments"))
    assert caught.value.orig.sqlstate == "25006"
    assert view.counts() == before
    with runner.engine.connect() as c:
        assert (
            c.execute(sa.text("SELECT count(*) FROM opsdesk_control.sandboxes")).scalar_one() == 0
        )


async def test_execution_trace_quarantines_rehashed_trial_with_wrong_audit_target(lab, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from agent_reliability_lab.evaluation import tables as t
    from agent_reliability_lab.evaluation.reporting import report
    from agent_reliability_lab.opsdesk.fixtures import digest
    from agent_reliability_lab.research.views import trial_matches_score

    runner, run = lab
    trial, _ = await run("benign_create")
    doc = report(runner.store, trial["experiment_id"], evaluator_version="1.7.0")
    score = doc["results"][0]
    assert trial_matches_score(doc, score, trial)
    assert score["reconciliation"]["complete"]
    eid = trial["trial_id"]
    monkeypatch.setenv(
        "OPSDESK_DASHBOARD_DATABASE_URL", runner.engine.url.render_as_string(hide_password=False)
    )
    ui = AppTest.from_string(
        f"""
import os
from agent_reliability_lab.dashboard.evidence import execution_trace
from agent_reliability_lab.research.views import ResearchView, readonly_engine
view = ResearchView(readonly_engine(os.environ["OPSDESK_DASHBOARD_DATABASE_URL"]))
execution_trace(view, view.report({doc["report_id"]!r}))
"""
    ).run()
    assert not ui.exception and not ui.error
    assert "Committed" in " ".join(x.proto.body for x in ui.get("html"))
    altered = trial["evidence"]
    audit = altered["audits"][0]
    assert audit["task_id"] != "task_001"
    audit["task_id"] = "task_001"
    with runner.engine.begin() as c:
        c.exec_driver_sql("ALTER TABLE opsdesk_evaluation.trials DISABLE TRIGGER USER")
        c.execute(
            t.trials.update()
            .filter_by(trial_id=eid)
            .values(evidence=altered, evidence_hash=digest(altered))
        )
        c.exec_driver_sql("ALTER TABLE opsdesk_evaluation.trials ENABLE TRIGGER USER")
    ui.run()
    assert not ui.exception
    assert "unverified for this trial" in ui.error[0].value
    assert "Committed" not in " ".join(x.proto.body for x in ui.get("html"))
    view = ResearchView(runner.engine)
    assert view.report(doc["report_id"])["results"] == doc["results"]
    assert view.trial(eid)["evidence_hash"] == digest(altered)
