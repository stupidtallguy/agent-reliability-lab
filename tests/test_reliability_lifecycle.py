import pytest

from agent_reliability_lab.reliability.verification import AttemptProof, logical_commitment

RECEIPT = {"data": {"task_id": "created"}, "error": None}
LOST = {"data": None, "error": {"code": "transport_unavailable"}}


@pytest.mark.parametrize(
    ("status", "response", "outcomes", "expected"),
    [
        ("succeeded", RECEIPT, [(True, RECEIPT)], "verified"),
        ("failed", RECEIPT, [(True, RECEIPT)], "contradictory"),
        ("failed", LOST, [(False, LOST)], "unresolved"),
        ("succeeded", RECEIPT, [], "unresolved"),
        ("succeeded", RECEIPT, [(False, LOST)], "contradictory"),
        ("succeeded", RECEIPT, [(True, RECEIPT), (False, LOST)], "verified"),
        ("failed", LOST, [(True, RECEIPT), (False, LOST)], "unresolved"),
        ("succeeded", RECEIPT, [(False, LOST), (True, RECEIPT)], "verified"),
        ("succeeded", RECEIPT, [(True, RECEIPT), (True, RECEIPT)], "verified"),
        ("succeeded", RECEIPT, [(True, {"data": {"task_id": "other"}})], "contradictory"),
    ],
)
def test_terminal_logical_status_and_receipt_must_match_the_sealed_attempt(
    status, response, outcomes, expected
):
    proofs = [
        AttemptProof({"status": "succeeded" if ok else "failed"}, result, i, i + 1)
        for i, (ok, result) in enumerate(outcomes, 1)
    ]
    assert logical_commitment({"status": status, "response": response}, proofs) == expected


@pytest.mark.parametrize(
    ("states", "markers", "expected", "fault_recovery"),
    [
        (["succeeded"], [], [], []),
        (["failed", "succeeded"], [1], [2], ["a2"]),
        (["failed", "failed", "succeeded"], [], [], [None, None]),
        (["failed", "failed", "succeeded"], [1], [3], ["a3", None]),
        (["failed", "failed", "succeeded"], [1, 2], [3], ["a3", "a3"]),
        (["failed", "succeeded", "failed"], [1], [2], ["a2", None]),
        (["failed", "succeeded"], [2], [], [None]),
    ],
)
def test_retry_aggregation_counts_receipt_reuse_by_actual_attempt_identity(
    states, markers, expected, fault_recovery
):
    from agent_reliability_lab.reliability.publication import retry_attribution

    proofs = [
        AttemptProof(
            {
                "attempt_id": f"a{i}",
                "ordinal": i,
                "status": status,
                "error_code": "transport_unavailable" if status == "failed" else None,
            },
            LOST if status == "failed" else RECEIPT,
            4 * i,
            4 * i + 2,
        )
        for i, status in enumerate(states, 1)
    ]
    successes = [p for p in proofs if p.attempt["status"] == "succeeded"]
    observations = [{"sequence": 4 * i + 1, "body": {"receipt_hash": "receipt"}} for i in markers]
    faults, retries, report = retry_attribution(proofs, successes, observations)
    assert [(r["attempt_id"], r["ordinal"]) for r in report["receipt_reuse_attempts"]] == [
        (f"a{i}", i) for i in expected
    ]
    assert [row["verified_recovery_attempt_id"] for row in report["fault_observations"]] == (
        fault_recovery
    )
    assert [r.identity for r in retries if r.outcome is True] == [f"a{i}" for i in expected]
    assert [r.outcome for r in faults] == [True if item else None for item in fault_recovery]
