import pytest

from agent_reliability_lab.research.statistics import paired_summary
from agent_reliability_lab.research.units import InvalidExperimentalUnit, validate_units


def row(n=1):
    return dict(
        pair_id=str(n),
        baseline_trial_id=f"b{n}",
        guarded_trial_id=f"g{n}",
        baseline_execution_id=f"eb{n}",
        guarded_execution_id=f"eg{n}",
        scenario_id="one",
        family_id="shared",
        verified=True,
        baseline=False,
        guarded=True,
    )


@pytest.mark.parametrize(
    "field,reason",
    [
        ("pair", "duplicate_underlying_trial_pair"),
        ("baseline_trial_id", "reused_trial_identity"),
        ("guarded_trial_id", "reused_trial_identity"),
        ("baseline_execution_id", "reused_execution_identity"),
        ("guarded_execution_id", "reused_execution_identity"),
    ],
)
def test_underlying_units_cannot_be_aliased(field, reason):
    a, b = row(), row(2)
    if field == "pair":
        b.update(
            {k: v for k, v in a.items() if k.endswith("trial_id") or k.endswith("execution_id")}
        )
    else:
        b[field] = a[field]
    with pytest.raises(InvalidExperimentalUnit, match=reason) as err:
        validate_units([a, b])
    assert err.value.exclusions == [dict(pair_id="2", reason=reason)]
    with pytest.raises(InvalidExperimentalUnit, match=reason):
        paired_summary([a, b])


def test_distinct_repeated_trials_remain_valid_clustered_units():
    rows = [row(i) for i in range(3)]
    validate_units(rows)
    s = paired_summary(rows)
    assert s["complete_verified_pairs"] == 3 and s["family_count"] == 1
    assert s["exact_mcnemar_p"] is None


def test_verified_unit_requires_actual_execution_identity():
    unit = row()
    unit["guarded_execution_id"] = None
    with pytest.raises(InvalidExperimentalUnit, match="missing_trial_or_execution_identity"):
        validate_units([unit])
