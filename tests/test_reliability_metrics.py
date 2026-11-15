import csv
import io
import json

import pytest

from agent_reliability_lab.reliability.diagnostics import provider_gaps
from agent_reliability_lab.reliability.metrics import (
    DEFINITIONS,
    Observation,
    evidence_quality,
    metric,
    notification_metrics,
    render,
    revised_metrics,
)


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


@pytest.mark.parametrize("name", list(DEFINITIONS))
def test_every_metric_handles_positive_negative_unknown_empty_and_unavailable(name):
    scope = "fixture"
    for population, expected in [
        ([Observation("a", True), Observation("b", False), Observation("c", None)], (1, 2, 0.5, 1)),
        ([Observation("false", False)], (0, 1, 0, 0)),
        ([Observation("unresolved", None)], (None, None, None, 1)),
        ([], (0, 0, None, 0)),
        (None, (None, None, None, None)),
    ]:
        record = next(
            m for m in revised_metrics({name: population}, scope=scope) if m["name"] == name
        )
        assert (
            tuple(record.get(k) for k in ("numerator", "denominator", "value", "unresolved"))
            == expected
        )


def test_receipt_without_fault_or_mutation_inventory_cannot_establish_recovery():
    measures = notification_metrics(
        {
            "notification_id": "n",
            "delivery": "unknown",
            "local_intent": "recorded",
            "acknowledged": False,
        },
        operation_id="op",
        mutation_count=None,
        receipt_reconciled=True,
        attempt_observations=[],
        faults=[],
        conflicts=[Observation("rejected", True)],
        dispatched=True,
    )
    by_name = {m["name"]: m for m in measures}
    assert by_name["verified_recovery"]["denominator"] == 0
    assert by_name["duplicate_effect"]["value"] is None
    assert by_name["unknown_commitment"]["value"] == 1
    assert by_name["conflicting_intent_rejection"]["value"] == 1


def test_uninspected_chain_is_separate_from_observed_incomplete_chain():
    rows = [
        {"status": "infrastructure_failure", "objective_success": None},
        {"reconciliation": {"complete": False, "errors": ["unavailable"]}},
    ]
    measures = {m["name"]: m for m in evidence_quality({"results": rows})}
    assert measures["chain_completeness"]["denominator"] == 1
    assert measures["chain_completeness"]["numerator"] == 0
    measures = {m["name"]: m for m in evidence_quality({"results": rows[:1]})}
    assert measures["chain_completeness"]["value"] is None


def test_current_exports_include_revision_and_predecessor_and_keep_legacy_csv():
    from agent_reliability_lab.reliability.metrics import VERSION

    document = {
        "version": VERSION,
        "report_id": "selected",
        "execution_id": "run",
        "revision": 2,
        "previous_report_id": "before",
        "provider": {"delivery": "delivered"},
        "metrics": revised_metrics(
            {"external_confirmation": [Observation("event", True)]}, scope="demo"
        ),
    }
    source = json.loads(render(document, "json"))
    rows = list(csv.DictReader(io.StringIO(render(document, "csv"))))
    assert all(
        row["revision"] == str(source["revision"])
        and row["previous_report_id"] == source["previous_report_id"]
        for row in rows
    )
    assert "- Revision 2" in render(document, "md")
    assert "- Predecessor `before`" in render(document, "md")
    assert "previous_report_id" not in render({**document, "version": "reliability-1.0.0"}, "csv")


@pytest.mark.parametrize(
    ("mutations", "delivery", "complete", "contradiction", "duplicate"),
    [
        (1, "delivered", 1, 0, 0),
        (1, "unknown", 0, 0, 0),
        (0, "failed", 0, 1, 0),
        (None, "delivered", 0, 0, None),
        (2, "delivered", 0, 0, 1),
        (1, "contradictory", 0, 1, 0),
    ],
)
def test_local_inventory_constrains_terminal_chain(
    mutations, delivery, complete, contradiction, duplicate
):
    rows = notification_metrics(
        {
            "notification_id": "n",
            "delivery": delivery,
            "local_intent": "recorded",
            "acknowledged": True,
        },
        operation_id="op",
        mutation_count=mutations,
        receipt_reconciled=True,
        attempt_observations=None,
        faults=[],
        conflicts=[],
        dispatched=True,
    )
    metrics = {row["name"]: row for row in rows}
    assert metrics["chain_completeness"]["value"] == complete
    assert metrics["contradiction"]["value"] == contradiction
    assert metrics["duplicate_effect"]["value"] == duplicate
    if mutations in (0, None):
        assert metrics["external_confirmation"]["value"] == 0


@pytest.mark.parametrize(
    ("mutations", "receipt", "deduplication", "contradiction"),
    [
        (0, True, None, 1),
        (2, True, None, 1),
        (None, True, None, 0),
        (1, False, None, 1),
        (1, None, None, 0),
        (1, True, 1, 0),
    ],
)
def test_deduplication_requires_one_mutation_and_a_reconciled_receipt(
    mutations, receipt, deduplication, contradiction
):
    rows = notification_metrics(
        {
            "notification_id": "n",
            "delivery": "unknown",
            "local_intent": "recorded",
            "acknowledged": True,
        },
        operation_id="op",
        mutation_count=mutations,
        receipt_reconciled=receipt,
        attempt_observations=[Observation("retry", True)],
        faults=[Observation("fault", True)],
        conflicts=[],
        dispatched=True,
    )
    by_name = {row["name"]: row for row in rows}
    assert by_name["retry_deduplication"]["value"] == deduplication
    assert by_name["verified_recovery"]["value"] == deduplication
    assert by_name["contradiction"]["value"] == contradiction
