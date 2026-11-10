import pytest

from agent_reliability_lab.research.identity import (
    UnverifiableImplementation,
    identity_status,
    require_compatible,
)
from agent_reliability_lab.research.statistics import paired_summary, unverified_descriptive
from agent_reliability_lab.research.units import InvalidExperimentalUnit

from .support import facts


def test_required_candidate_and_historical_identity():
    _, r = facts()
    assert identity_status(r)["missing"] == []
    require_compatible([r, r.model_copy(deep=True)])
    for key in identity_status(r)["required"]:
        broken = r.model_copy(deep=True)
        broken.scoring_provenance.pop(key)
        with pytest.raises(UnverifiableImplementation):
            require_compatible([r, broken])
    old = r.model_copy(deep=True)
    old.evaluator_version = "1.0.1"
    old.scoring_provenance = {"evaluator_source_hash": "a" * 64}
    assert "scoring_implementation_hash" in identity_status(old)["not_required"]
    require_compatible([old])
    old.scoring_provenance = {}
    assert identity_status(old)["status"] == "historically_unavailable"
    with pytest.raises(UnverifiableImplementation):
        require_compatible([old])


def test_identity_free_observations_have_no_verified_or_inferential_mode():
    rows = [dict(pair_id=str(i), verified=True, baseline=False, guarded=True) for i in range(2)]
    with pytest.raises(InvalidExperimentalUnit, match="missing_trial_or_execution_identity"):
        paired_summary(rows)
    result = unverified_descriptive(rows)
    assert result["verification"] == "unverified_math"
    assert result["arithmetic_difference"] == 1
    assert "complete_verified_pairs" not in result and "cluster_bootstrap_interval" not in result


@pytest.mark.parametrize("configured", [True, False])
def test_paired_scope_uses_frozen_plan_not_observed_outcome_eligibility(configured):
    from types import SimpleNamespace

    from agent_reliability_lab.research.measurements import summarize_outcomes

    _, result = facts()
    result.status = "infrastructure_failure"
    result.eligible = result.attack_eligible = False
    result.experimental["planned_trial"] = dict(
        status="known", attack_count=int(configured), fault_count=0, benign_control=False
    )
    row = dict(
        pair_id="pair",
        verified=True,
        family_id="family",
        scenario_id="scenario",
        baseline_trial_id="left",
        guarded_trial_id="right",
        baseline_execution_id="left-execution",
        guarded_execution_id="right-execution",
    )
    store = SimpleNamespace(evaluations=SimpleNamespace(scores=lambda _: [result]))
    analysis = dict(
        rows=[row],
        selected_scores=[dict(trial_id=t, scoring_id=result.scoring_id) for t in ("left", "right")],
    )
    summary = summarize_outcomes(store, analysis)["attack_success"]
    assert summary["not_applicable_pairs"] == (0 if configured else 1)
    assert summary["incomplete_or_unknown_pairs"] == (1 if configured else 0)
    assert summary["complete_verified_pairs"] == 0


@pytest.mark.parametrize("candidate", [True, False])
def test_packaged_lock_identity_is_explicit_and_preserves_legacy_absence(tmp_path, candidate):
    import hashlib

    from agent_reliability_lab.evaluation.versions import implementation_identity

    package = tmp_path / "package"
    (package / "resources").mkdir(parents=True)
    (package / "example.py").write_text("# synthetic package\n")
    data = b"synthetic locked dependency manifest"
    (package / "resources/uv.lock").write_bytes(data)
    identity = implementation_identity(package, tmp_path / "absent.lock", packaged_lock=candidate)
    assert identity["dependency_lock_hash"] == (
        hashlib.sha256(data).hexdigest() if candidate else None
    )
