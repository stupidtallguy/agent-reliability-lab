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
