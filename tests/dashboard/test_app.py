import pytest
from streamlit.testing.v1 import AppTest

from agent_reliability_lab.dashboard.app import PAGES
from tests.dashboard.support import app


@pytest.mark.parametrize("page", PAGES)
def test_each_readonly_page_renders_without_writes(page):
    at = AppTest.from_function(app, default_timeout=20).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception
    assert not at.error
    assert not at.button  # downloads and selectors only, no mutation buttons


def test_missing_host_database_is_an_actionable_welcome(monkeypatch):
    monkeypatch.delenv("OPSDESK_DASHBOARD_DATABASE_URL", raising=False)
    from agent_reliability_lab.dashboard.app import get_view

    get_view.clear()
    from agent_reliability_lab.dashboard import app as module

    at = AppTest.from_file(module.__file__).run()
    assert not at.exception
    assert any("opsdesk-lab demo" in code.value for code in at.code)


def test_content_is_bounded_and_untrusted_text_remains_data():
    from agent_reliability_lab.dashboard.app import bounded

    payload = {"body": "<script>synthetic</script>", "api_key": "synthetic-value"}
    result = bounded(payload)
    assert "<script>" in str(result)
    assert result["api_key"] != "synthetic-value"
    assert bounded("x" * 100_001)["preview_truncated"]
