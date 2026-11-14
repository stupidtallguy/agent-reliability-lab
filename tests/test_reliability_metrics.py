import csv
import io
import json

from agent_reliability_lab.reliability.diagnostics import provider_gaps
from agent_reliability_lab.reliability.metrics import evidence_quality, metric, render


def test_quality_distinguishes_unresolved_from_determinate_failures():
    report = {
        "evaluator_version": "1.7.0",
        "results": [
            {
                "objective_success": False,
                "eligible": True,
                "reconciliation": {"complete": True, "errors": []},
            },
            {
                "objective_success": None,
                "eligible": False,
                "reconciliation": {
                    "complete": False,
                    "errors": [{"code": "receipt_argument_conflict"}],
                },
            },
        ],
    }
    assert [(m["numerator"], m["denominator"]) for m in evidence_quality(report)] == [(1, 2)] * 4
    report["results"][1]["reconciliation"] = {}
    assert evidence_quality(report)[-1]["reason"] == "population_unavailable"


def test_exports_use_same_counts_and_never_render_unknown_as_zero():
    document = {
        "report_id": "report",
        "execution_id": "execution",
        "revision": 1,
        "provider": {"delivery": "unknown"},
        "metrics": [
            metric("unknown_outcome", 1, 1, "Synthetic run"),
            metric("external_confirmation", None, None, "Synthetic run"),
        ],
    }
    source = json.loads(render(document, "json"))
    rows = list(csv.DictReader(io.StringIO(render(document, "csv"))))
    md = render(document, "md")
    assert source["metrics"][0]["numerator"] == int(rows[0]["numerator"]) == 1
    assert source["metrics"][1]["value"] is None and rows[1]["value"] == ""
    assert "| external_confirmation | Unavailable | Unavailable | Unavailable |" in md
    assert "Delivery outcome **unknown**" in md
    assert all(render(document, name) == render(document, name) for name in ("json", "csv", "md"))


def test_missing_provider_ack_and_missing_delivery_are_separate():
    evidence = {"provider_attempts": [1], "acknowledged": False, "delivery": "unknown"}
    assert provider_gaps(evidence) == [
        "missing_provider_acknowledgment",
        "missing_delivery_confirmation",
    ]
    assert provider_gaps({**evidence, "delivery": "delivered"}) == [
        "missing_provider_acknowledgment"
    ]
