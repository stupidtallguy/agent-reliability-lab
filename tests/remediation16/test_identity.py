from types import SimpleNamespace

import pytest

from agent_reliability_lab.agent.provenance import seal
from agent_reliability_lab.agent.provenance_v2 import verify_model_identity


def evidence():
    records = []
    for kind, ref, body in [
        ("execution_created", "run", {}),
        (
            "model_started",
            "first",
            dict(execution_id="run", request_id="first", provider="fake", model="scripted-v1"),
        ),
        (
            "model_started",
            "second",
            dict(execution_id="run", request_id="second", provider="fake", model="scripted-v1"),
        ),
    ]:
        records.append(
            seal(
                "run",
                len(records) + 1,
                kind,
                ref,
                body,
                records[-1]["record_hash"] if records else None,
            )
        )
    return SimpleNamespace(
        execution_id="run",
        provenance=records,
        execution={"config": {"model": {"provider": "fake", "model_id": "scripted-v1"}}},
        requests=[{"request_id": "first"}, {"request_id": "second"}],
    )


def reseal(e):
    e.provenance = [seal(e.execution_id, 1, "execution_created", "run", {}, None)] + e.provenance[
        1:
    ]
    for i in range(1, len(e.provenance)):
        r = e.provenance[i]
        e.provenance[i] = seal(
            e.execution_id,
            i + 1,
            r["kind"],
            r["reference"],
            r["body"],
            e.provenance[i - 1]["record_hash"],
        )


def test_matching_multiple_requests_and_redacted_configuration():
    e = evidence()
    e.execution["config"]["model"]["script"] = []
    verify_model_identity(e)


@pytest.mark.parametrize(
    "side,field,value,code",
    [
        ("captured", "provider", "openai", "contradictory_model_identity_provider"),
        ("captured", "model_id", "other", "contradictory_model_identity_model"),
        ("captured", "provider", None, "missing_or_malformed_model_identity_provider"),
        ("captured", "model_id", None, "missing_or_malformed_model_identity_model"),
        ("sealed", "provider", None, "missing_or_malformed_model_identity_provider"),
        ("sealed", "model", None, "missing_or_malformed_model_identity_model"),
        ("sealed", "provider", "openai", "contradictory_model_identity_provider"),
        ("sealed", "model", "OTHER", "contradictory_model_identity_model"),
    ],
)
def test_each_identity_boundary_has_specific_diagnostic(side, field, value, code):
    e = evidence()
    if side == "captured":
        e.execution["config"]["model"][field] = value
    else:
        e.provenance[-1]["body"][field] = value
        reseal(e)
    with pytest.raises(ValueError, match=code):
        verify_model_identity(e)


def test_model_identifiers_are_case_sensitive_and_provider_names_are_canonical():
    e = evidence()
    e.execution["config"]["model"]["provider"] = "FAKE"
    verify_model_identity(e)
    e.execution["config"]["model"]["model_id"] = "Scripted-v1"
    with pytest.raises(ValueError, match="contradictory_model_identity_model"):
        verify_model_identity(e)


def test_identity_diagnostic_never_echoes_supplied_secret_or_redaction():
    e = evidence()
    secret = "synthetic-sensitive-model-identity"
    e.execution["config"]["model"]["model_id"] = secret
    with pytest.raises(ValueError) as caught:
        verify_model_identity(e)
    assert secret not in str(caught.value)
    e.execution["config"]["model"]["model_id"] = "[REDACTED]"
    with pytest.raises(ValueError, match="unsupported_redacted_model_identity_model"):
        verify_model_identity(e)


def test_frozen_v15_scorer_and_projection_files_remain_available():
    import json
    from pathlib import Path

    from agent_reliability_lab.evaluation.preservation import verify_sources

    root = Path(__file__).parents[2]
    hashes = json.loads((root / "benchmarks/research/historical-scorers-v1.5.json").read_text())
    assert len(hashes) == 3 and all(verify_sources(root, hashes).values())


def test_missing_completed_decision_provenance_is_not_silently_accepted():
    from agent_reliability_lab.agent.provenance_v2 import verify_decision_sources

    e = evidence()
    e.requests[0].update(status="completed", turn=0, calls=[])
    e.requests[1].update(status="started", turn=1, calls=[])
    with pytest.raises(ValueError, match="missing_sealed_decision"):
        verify_decision_sources(e)


def test_malformed_sealed_identity_is_unverifiable_not_an_attribute_error():
    e = evidence()
    e.provenance[-1]["body"] = []
    reseal(e)
    with pytest.raises(ValueError, match="unsupported_malformed_sealed_request_identity"):
        verify_model_identity(e)


@pytest.mark.parametrize(
    "reply,code",
    [
        (None, "unsupported_malformed_sealed_decision"),
        ({}, "missing_sealed_original_proposals"),
        ({"calls": "invalid"}, "unsupported_malformed_original_decision"),
    ],
)
def test_malformed_original_decision_has_a_safe_diagnostic(reply, code):
    from agent_reliability_lab.agent.provenance_v2 import verify_decision_sources

    e = evidence()
    e.requests[0].update(status="completed", turn=0, calls=[])
    e.requests[1].update(status="started", turn=1, calls=[])
    e.provenance.append(
        seal(
            "run",
            4,
            "model_completed",
            "first",
            {"execution_id": "run", "request_id": "first", "turn": 0, "reply": reply},
            e.provenance[-1]["record_hash"],
        )
    )
    with pytest.raises(ValueError, match=code):
        verify_decision_sources(e)
