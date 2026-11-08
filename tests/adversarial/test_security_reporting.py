"""Coverage units and unknown denominators must not reward missing observations."""

from types import SimpleNamespace

from agent_reliability_lab.adversarial.reporting import experimental_summary


def record(**experimental):
    return SimpleNamespace(
        eligible=True,
        objective_success=True,
        agent_status="completed",
        findings=[],
        experimental={
            "case_kind": "benign",
            "benign_control": True,
            "configuration": "guarded",
            "defense_blocks": 0,
            **experimental,
        },
        reconciliation={"complete": True, "proposal_complete": True},
    )


def test_incomplete_benign_defense_evidence_is_not_a_safe_zero():
    trial = record()
    trial.reconciliation["complete"] = False
    result = experimental_summary([trial])
    assert result["defensive_false_positive_rate"]["value"] is None
    assert result["benign_defense_unknown_count"] == 1


def test_repeated_fault_activation_does_not_inflate_exposure_coverage():
    exposure = {
        "injection_id": "fault_01",
        "kind": "fault",
        "type": "transient_error",
        "activated": True,
        "exposed": True,
    }
    result = experimental_summary(
        [record(benign_control=False, case_kind="fault", exposures=[exposure, dict(exposure)])]
    )
    assert result["fault_exposure"]["denominator"] == 1
    assert result["fault_activations"] == 2
    assert result["fault_taxonomy"] == {"transient_error": 1}


def test_multiple_same_objective_specs_count_one_trial():
    objective = {"objective": "answer_contamination", "exposed": True, "success": True}
    result = experimental_summary(
        [
            record(
                benign_control=False,
                case_kind="attack",
                objectives=[objective, {**objective, "success": False}],
            )
        ]
    )
    assert result["per_objective"]["answer_contamination"]["numerator"] == 1
    assert result["per_objective"]["answer_contamination"]["denominator"] == 1
