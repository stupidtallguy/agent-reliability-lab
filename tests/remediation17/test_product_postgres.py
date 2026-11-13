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
