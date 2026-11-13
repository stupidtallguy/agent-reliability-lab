import pytest
from sqlalchemy.exc import OperationalError
from streamlit.testing.v1 import AppTest

from agent_reliability_lab.dashboard.app import PAGES
from agent_reliability_lab.dashboard.design import COLORS, metric_text
from agent_reliability_lab.dashboard.evidence import timeline, timeline_rows
from agent_reliability_lab.dashboard.pages import matched_report
from tests.dashboard.support import MemoryView, app


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


@pytest.mark.parametrize(
    "purpose,demo,split,label",
    [
        ("scripted_infrastructure_validation", True, "development", "Synthetic demonstration"),
        (
            "scripted_infrastructure_validation",
            False,
            "development",
            "Scripted infrastructure validation",
        ),
        ("live_evaluation", False, "held_out", "Live-model evaluation"),
    ],
)
def test_overview_identifies_purpose_and_split(monkeypatch, purpose, demo, split, label):
    def configure(self, _):
        self.document["manifest"].update(purpose=purpose, demonstration=demo)
        self.document["results"][0]["split"] = split
        return self.document

    monkeypatch.setattr(MemoryView, "report", configure)
    at = AppTest.from_function(app).run()
    assert not at.exception
    markup = next(
        row.proto.body
        for row in at.get("html")
        if '<div class="lab-cohort-label">' in row.proto.body
    )
    assert label in markup
    assert f"splits · {split.replace('_', '-')}" in markup


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"value": 0.75, "numerator": 3, "denominator": 4}, ("75.0%", "3 / 4", "Measured")),
        ({"value": 0, "numerator": 0, "denominator": 4}, ("0.0%", "0 / 4", "Measured")),
        (
            {"value": None, "numerator": 0, "denominator": 0},
            ("Unavailable", "0 / 0", "Insufficient evidence"),
        ),
        (
            {"status": "not_applicable"},
            ("Not applicable", "Unavailable / Unavailable", "Not applicable"),
        ),
    ],
)
def test_metric_format_preserves_counts_and_unknown(record, expected):
    assert metric_text(record) == expected


def test_overview_six_kpis_show_evaluator_and_denominator():
    at = AppTest.from_function(app).run()
    markup = next(
        element.proto.body
        for element in at.get("html")
        if "lab-kpi-grid" in element.proto.body and "<article" in element.proto.body
    )
    assert markup.count("<article") == markup.count("Evaluator 1.7.0") == 6
    assert "1 / 1" in markup and "Insufficient evidence" in markup


def test_experiment_search_filters_inventory_and_handles_no_matches():
    at = AppTest.from_function(app).run()
    at.sidebar.radio[0].set_value("Experiments").run()
    at.text_input[0].set_value("attack_hijack").run()
    assert at.dataframe[0].value.iloc[0]["Configuration"] == "Baseline"
    at.text_input[0].set_value("no matching experiment").run()
    assert any("No experiments match" in item.value for item in at.info)
    assert not at.dataframe


def test_report_selector_never_mixes_or_falls_back_on_version_mismatch(monkeypatch):
    def index(self, experiment_id):
        return [
            {"report_id": self.document["report_id"], "evaluator": "1.7.0"},
            {"report_id": "old_revision", "evaluator": "1.1.0"},
        ]

    monkeypatch.setattr(MemoryView, "report_index", index)
    at = AppTest.from_function(app).run()
    at.sidebar.selectbox[1].set_value("1.1.0").run()
    assert len(at.sidebar.selectbox[2].options) == 1
    assert at.error and "selected evidence" in at.error[0].value
    assert not any("<article" in element.proto.body for element in at.get("html"))


def test_empty_inventory_and_missing_report_states(monkeypatch):
    monkeypatch.setattr(MemoryView, "report_index", lambda *args: [])
    at = AppTest.from_function(app).run()
    assert any("no saved report" in item.value for item in at.info)
    monkeypatch.setattr(MemoryView, "experiment_inventory", lambda *args, **kwargs: [])
    at.run()
    assert any("inventory page is empty" in item.value for item in at.info)


def test_database_failure_never_displays_raw_diagnostics(monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("sensitive SQL", {}, RuntimeError("private connection info"))

    monkeypatch.setattr(MemoryView, "experiment_inventory", fail)
    at = AppTest.from_function(app).run()
    assert not at.exception
    assert "unavailable" in at.error[0].value
    assert "sensitive" not in at.error[0].value


def test_timeline_joins_duration_and_escapes_untrusted_event_fields(monkeypatch):
    evidence = {
        "attempts": [{"attempt_id": "attempt", "duration_ms": 11}],
        "events": [
            {
                "sequence": 8,
                "event_type": "tool_call_failed",
                "payload": {
                    "attempt_id": "attempt",
                    "tool": "<img src=x onerror=alert(1)>",
                    "error_code": "permission_denied",
                    "correlation_id": "correlation",
                },
            }
        ],
    }
    rows = list(timeline_rows(evidence))
    assert rows[0][:3] == ("Tool response", "Denied", "bad")
    assert "11 ms duration" in rows[0][3] and "events/8" in rows[0][3]
    from agent_reliability_lab.dashboard import evidence as module

    output = []
    monkeypatch.setattr(module.st, "html", output.append)
    timeline(rows)
    assert "&lt;img" in output[0] and "<img" not in output[0]


def test_paired_supplement_requires_exact_score_ids_and_evaluator(monkeypatch):
    view = MemoryView()
    trial_id = view.trial_value["trial_id"]
    rows = [{"baseline_trial_id": trial_id}]
    refs = [{"trial_id": trial_id, "scoring_id": "expected"}]
    records = [
        {"report_id": "wrong_version", "evaluator": "1.1.0", "score_ids": ["expected"]},
        {"report_id": "wrong_scores", "evaluator": "1.7.0", "score_ids": ["another"]},
    ]
    monkeypatch.setattr(view, "report_index", lambda _: records)
    monkeypatch.setattr(view, "report", lambda report_id: report_id)
    assert matched_report(view, rows, refs, "baseline", "1.7.0") is None
    records.append({"report_id": "matched", "evaluator": "1.7.0", "score_ids": ["expected"]})
    assert matched_report(view, rows, refs, "baseline", "1.7.0") == "matched"


def contrast(foreground, background):
    def luminance(color):
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum(
            w * (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
            for w, v in zip((0.2126, 0.7152, 0.0722), channels, strict=True)
        )

    dark, light = sorted([luminance(COLORS[foreground]), luminance(COLORS[background])])
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize(
    "foreground,background",
    [
        ("ink", "white"),
        ("ink", "canvas"),
        ("muted", "white"),
        ("muted", "canvas"),
        ("blue-ink", "blue-wash"),
        ("purple-ink", "purple-wash"),
        ("coral-ink", "coral-wash"),
        ("green-ink", "green-wash"),
        ("white", "royal"),
    ],
)
def test_normal_text_color_pairs_meet_aa_contrast(foreground, background):
    assert contrast(foreground, background) >= 4.5
