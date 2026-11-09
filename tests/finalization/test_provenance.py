import copy

import pytest

from agent_reliability_lab.agent.provenance import seal, verify


@pytest.mark.parametrize("corruption", ["body", "delete", "reorder", "owner", "previous"])
def test_chain_detects_each_mutation(corruption):
    first = seal("run", 1, "execution_created", "run", {"safe": 1}, None)
    second = seal("run", 2, "model_started", "request", {"turn": 0}, first["record_hash"])
    records = copy.deepcopy([first, second])
    assert verify(records, "run") == second["record_hash"]
    if corruption == "body":
        records[1]["body"]["turn"] = 1
    elif corruption == "delete":
        records.pop(0)
    elif corruption == "reorder":
        records.reverse()
    elif corruption == "owner":
        records[1]["execution_id"] = "other"
    else:
        records[1]["previous_hash"] = "changed"
    with pytest.raises(ValueError, match="contradictory"):
        verify(records, "run")


def test_unsealed_legacy_is_explicitly_unsupported():
    with pytest.raises(ValueError, match="missing_immutable"):
        verify([], "run")
    with pytest.raises(ValueError, match="unsupported_unsealed"):
        verify([seal("run", 1, "model_started", "r", {}, None)], "run")
