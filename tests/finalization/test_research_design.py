import json
from pathlib import Path

import pytest

from agent_reliability_lab.research.contracts import SplitManifest
from agent_reliability_lab.research.statistics import exact_mcnemar, paired_summary


def test_catalog_preserves_all_existing_development_scenarios():
    root = Path(__file__).parents[2]
    split = SplitManifest.model_validate_json(
        (root / "benchmarks/research/split-development.json").read_text()
    )
    assert len(split.templates) == 38
    assert {t.split for t in split.templates} == {"development"}
    assert len({t.family_id for t in split.templates}) == 1
    assert not split.generalization_validated
    held = SplitManifest.model_validate_json(
        (root / "benchmarks/research/split-held_out.json").read_text()
    )
    assert held.templates == []


def test_semantic_family_overlap_rejected_even_with_different_hashes():
    root = Path(__file__).parents[2]
    payload = json.loads((root / "benchmarks/research/split-development.json").read_text())
    payload["templates"][1]["split"] = "held_out"
    payload["templates"][1]["content_hash"] = "f" * 64
    with pytest.raises(ValueError, match="family crosses"):
        SplitManifest.model_validate_json(json.dumps(payload))


def test_catalog_mechanisms_use_frozen_harness_categories():
    root = Path(__file__).parents[2]
    split = SplitManifest.model_validate_json(
        (root / "benchmarks/research/split-development.json").read_text()
    )
    items = {t.scenario_id: t for t in split.templates}
    assert items["attack_hijack"].mechanism.startswith("attack:")
    assert items["fault_transient"].mechanism == "fault:transient_error"
    assert items["benign_order"].mechanism == "benign_control"


def test_exact_mcnemar_reference_values():
    assert exact_mcnemar(0, 0) == 1
    assert exact_mcnemar(0, 4) == 0.125
    assert exact_mcnemar(4, 0) == 0.125
    assert exact_mcnemar(2, 2) == 1


def test_clustered_repeats_do_not_receive_independent_pair_test():
    rows = [
        dict(
            pair_id=str(i),
            family_id="shared",
            scenario_id="one",
            verified=True,
            baseline=False,
            guarded=True,
        )
        for i in range(5)
    ]
    summary = paired_summary(rows, seed=9)
    assert summary["paired_risk_difference"] == 1
    assert summary["family_count"] == 1
    assert summary["exact_mcnemar_p"] is None
    assert summary["cluster_bootstrap_interval"] is None


def test_seeded_family_analysis_and_missing_pair_sensitivity():
    rows = [
        dict(
            pair_id=str(i),
            family_id=str(i),
            scenario_id=str(i),
            verified=True,
            baseline=False,
            guarded=True,
        )
        for i in range(4)
    ]
    rows.append(dict(pair_id="missing", verified=False, baseline=True, guarded=None))
    summary = paired_summary(
        rows, seed=3, independent_units_justification="Independent synthetic families."
    )
    assert summary == paired_summary(
        rows, seed=3, independent_units_justification="Independent synthetic families."
    )
    assert summary["incomplete_or_unknown_pairs"] == 1
    assert summary["pair_coverage"] == 0.8
    assert summary["exact_mcnemar_p"] is None
    complete = paired_summary(
        rows[:4], seed=3, independent_units_justification="Independent synthetic families."
    )
    assert complete["exact_mcnemar_p"] == 0.125
    assert summary["exclusion_sensitivity_bounds"] == [0.6, 1]
    assert summary["cluster_bootstrap_interval"] == [1, 1]


def test_unknown_outcomes_not_imputed_or_called_failures():
    summary = paired_summary([dict(pair_id="unknown", verified=True, baseline=None, guarded=False)])
    assert summary["complete_verified_pairs"] == 0
    assert summary["paired_risk_difference"] is None
    assert summary["wilson_descriptive_guarded"] is None
    assert summary["exclusion_sensitivity_bounds"] == [-1, 1]
