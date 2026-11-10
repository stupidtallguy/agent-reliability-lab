import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

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
