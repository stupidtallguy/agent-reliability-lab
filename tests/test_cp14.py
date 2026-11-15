import json
import subprocess
import sys
import uuid
from dataclasses import replace
from decimal import Decimal

import pytest

from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research import benchmark, cluster_design
from agent_reliability_lab.research.cluster_design import (
    cluster_contrast,
    pair_loss_probability,
    plan_power,
    two_sided_t,
)
from agent_reliability_lab.research.confirmatory import (
    _check_power,
    draft_allocation,
    preflight,
    reserve_future_call,
    sealed_clusters,
    verify_allocation,
)
from agent_reliability_lab.research.confirmatory_analysis import (
    _measure,
    analysis_draft,
    analyze_allocation,
    verify_analysis,
)
from agent_reliability_lab.research.confirmatory_contracts import (
    BudgetUsage,
    ConfirmatoryAllocation,
    EvidenceSelection,
    FutureBudget,
    ModelIdentity,
    ReservationRequest,
)
from agent_reliability_lab.research.heldout import _findings, comparison_inputs
from agent_reliability_lab.research.heldout_contracts import (
    LeakagePolicy,
    PowerDesign,
    PowerScenario,
)
from agent_reliability_lab.research.heldout_design import draft_design
from agent_reliability_lab.research.persistence import ResearchStore


class MemoryStore:
    def __init__(self):
        self.records = {}

    def reference(self, item):
        return ResearchStore.reference(self, item)

    def add(self, item):
        ref = self.reference(item)
        self.records[ref.content_hash] = item
        return ref

    def get(self, ref):
        item = self.records.get(ref.content_hash)
        if item is None or self.reference(item) != ref:
            raise ValueError("missing or conflicting frozen reference")
        return item


def parent_protocol():
    dataset, parent = benchmark.starter_draft(repetitions=2)
    item = "benign_create"
    return dataset, parent.model_copy(
        update={
            "scenarios": [item],
            "planned_pairs": 2,
            "scripts": {item: parent.scripts[item]},
        }
    )


def register_inputs(store, append):
    dataset, parent = parent_protocol()
    append(dataset)
    parent_ref = append(parent)
    design = draft_design(store, parent_ref, "cp14_design", "3" * 64, 1, None)
    refs = [append(value) for value in design.values()]
    return parent_ref, refs[-1]


def budget():
    return FutureBudget(
        models=[ModelIdentity(provider="future_provider", model_id="future-model")],
        configuration_hash="1" * 64,
        max_model_calls=5,
        max_calls_per_scenario=4,
        max_total_tokens=100,
        max_cost_usd=Decimal("0.05"),
        max_duration_ms=1000,
        max_retries_per_scenario=1,
    )


@pytest.fixture
def frozen():
    store = MemoryStore()
    _, plan = register_inputs(store, store.add)
    allocation = draft_allocation(
        store,
        plan,
        identity="cp14_synthetic",
        count=1,
        repetitions=2,
        target=0.8,
        budget=budget(),
        synthetic=True,
    )
    return store, store.add(allocation), allocation


def test_new_leakage_policy_checks_cross_family_neighbors_and_payload_reuse():
    dataset, _ = parent_protocol()
    source = next(row for row in comparison_inputs(dataset) if row.attack_families and row.attacks)
    left = replace(source, partition="held_out")
    alias = replace(
        left,
        identity="opaque_alias",
        content_hash="0" * 64,
        normalized_hash="1" * 64,
        executable_hash="2" * 64,
    )
    assert not _findings(left, alias, LeakagePolicy())
    near = replace(alias, families=frozenset(["new_family"]))
    current = {finding["check"] for finding in _findings(left, near, LeakagePolicy())}
    assert {"lexical_similarity", "structural_similarity"} <= current
    assert not _findings(left, near, LeakagePolicy(audit_version="1.0.0"))
    attack = replace(alias, attack_families=frozenset(["new_attack_family"]))
    assert [f["check"] for f in _findings(left, attack, LeakagePolicy())] == [
        "reused_attack_payload"
    ]
    assert any(f["check"] == "exact_content" for f in _findings(left, left, LeakagePolicy()))
    cross = replace(left, partition="development")
    assert any(f["check"] == "template_family" for f in _findings(left, cross, LeakagePolicy()))


def scenario(name, repetitions, **overrides):
    return PowerScenario(
        **(
            {
                "identity": name,
                "rationale": "Controlled assumptions for a method test.",
                "expected_difference": 0.10,
                "discordance": 0.3,
                "cluster_sign_icc": 0.1,
                "repetitions_per_cluster": repetitions,
                "pair_missing": 0.8,
                "pair_excluded": 0.7,
                "cluster_dropout": 0.05,
            }
            | overrides
        )
    )


def test_power_groups_schedules_and_applies_independent_loss(monkeypatch):
    small, large = scenario("small_schedule", 2), scenario("large_schedule", 4)
    assert pair_loss_probability(small) == pytest.approx(0.94)
    design = PowerDesign(
        simulations=200,
        cluster_grid=[20, 40],
        scenarios=[small, large],
        planning_basis="externally_justified",
        justification="Explicit test inputs.",
        minimum_meaningful_difference=0.1,
    )

    def controlled(design, scenario, effect, *, legacy=False):
        count = design.simulations if effect else 0
        return 17, [
            [count if scenario.repetitions_per_cluster == 2 else 0, 200, 20, 40],
            [count, 200, 40, 80],
        ]

    monkeypatch.setattr(cluster_design, "_simulate", controlled)
    result = plan_power(design)
    assert result["pair_loss_model"] == "independent_union" and result["planning_clusters"] is None
    assert result["feasible_designs"] == [
        {
            "repetitions_per_cluster": 2,
            "scenario_ids": ["small_schedule"],
            "targets": {"0.8": 20, "0.9": 20},
        },
        {
            "repetitions_per_cluster": 4,
            "scenario_ids": ["large_schedule"],
            "targets": {"0.8": 40, "0.9": 40},
        },
    ]
    assert result["results"][0]["combined_pair_loss"] == pytest.approx(0.94)


def test_preflight_power_checks_selected_grid_point(frozen, monkeypatch):
    store, _, allocation = frozen
    protocol = store.get(allocation.protocol)
    design = PowerDesign(
        planning_basis="externally_justified",
        justification="Test-only justification",
        minimum_meaningful_difference=0.1,
        minimum_effect_justification="Test-only rationale",
    )
    protocol = protocol.model_copy(update={"power": design})
    monkeypatch.setattr(
        "agent_reliability_lab.research.confirmatory.plan_power",
        lambda _: {
            "feasible_designs": [
                {"repetitions_per_cluster": 2, "scenario_ids": ["min"], "targets": {"0.8": 20}}
            ],
            "results": [
                {
                    "scenario": "min",
                    "rows": [
                        {
                            "planned_clusters": 40,
                            "null_calibrated": False,
                            "power_monte_carlo_interval": [0.85, 0.95],
                        }
                    ],
                }
            ],
        },
    )
    failures = []
    assert (
        _check_power(protocol, allocation.model_copy(update={"cluster_count": 40}), failures) == 20
    )
    assert failures == ["selected_allocation_fails_power_or_null_calibration"]
    failures.clear()
    assert (
        _check_power(
            protocol, allocation.model_copy(update={"repetitions_per_cluster": 4}), failures
        )
        is None
    )
    assert failures == ["power_schedule_mismatch"]


def test_sealed_allocation_preserves_cluster_members_and_never_invents_clusters(frozen):
    _, _, allocation = frozen
    inventory = [
        {"cluster": "a" * 64, "scenario": "1" * 64},
        {"cluster": "a" * 64, "scenario": "2" * 64},
        {"cluster": "b" * 64, "scenario": "3" * 64},
    ]
    result = sealed_clusters(inventory, allocation.protocol, 42, 2, 4)
    assert result == sealed_clusters(list(reversed(inventory)), allocation.protocol, 42, 2, 4)
    assert {len(c.scenarios) for c in result} == {1, 2}
    assert all(sum(p.first_arm == "baseline" for p in row.pairs) == 2 for row in result)
    assert len({p.identity for c in result for p in c.pairs}) == 8
    with pytest.raises(ValueError, match="exceeds eligible"):
        sealed_clusters(inventory, allocation.protocol, 42, 3, 4)


def test_allocation_recovers_exact_slots_and_rejects_tampering(frozen):
    store, _, allocation = frozen
    verify_allocation(store, allocation)
    data = allocation.model_dump(mode="json")
    original = data["clusters"][0]["pairs"][0]["identity"]
    data["clusters"][0]["pairs"][0]["identity"] = "e" * 64
    forged = ConfirmatoryAllocation.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError, match="differs from reconstructed"):
        verify_allocation(store, forged)
    data["clusters"][0]["pairs"][1]["identity"] = "e" * 64
    with pytest.raises(ValueError, match="repeats"):
        ConfirmatoryAllocation.model_validate_json(json.dumps(data))
    data["clusters"][0]["pairs"][0]["identity"] = original
    with pytest.raises(ValueError, match="seed"):
        verify_allocation(store, allocation.model_copy(update={"seed": 99}))
    with pytest.raises(ValueError, match="at least 2"):
        cluster = allocation.clusters[0]
        verify_allocation(
            store,
            allocation.model_copy(
                update={
                    "clusters": [cluster.model_copy(update={"pairs": cluster.pairs[:1]})],
                }
            ),
        )


def test_preflight_blocks_missing_provenance_and_unjustified_power(frozen, monkeypatch):
    store, ref, allocation = frozen
    monkeypatch.delenv("OPSDESK_PRIVATE_HELDOUT_CATALOG", raising=False)
    unavailable = preflight(store, ref, authorized=True)
    assert preflight(store, allocation.plan, authorized=True)["codes"] == [
        "allocation_missing",
        "private_catalog_unavailable",
    ]
    assert (
        unavailable["status"] == "blocked" and "private_catalog_unavailable" in unavailable["codes"]
    )
    assert "minimum_meaningful_effect_unjustified" in unavailable["codes"]
    assert "synthetic_allocation_ineligible" in unavailable["codes"]
    monkeypatch.setattr(
        "agent_reliability_lab.research.confirmatory.audit_registered",
        lambda *a, **kw: {
            "eligible_template_families": 0,
            "passed": False,
            "private_origin_counts": {"synthetic_fixture": 1},
        },
    )
    result = preflight(store, ref, authorized=True)
    assert set(result["codes"]) >= {
        "leakage_audit_failed",
        "confirmatory_provenance_ineligible",
        "insufficient_eligible_template_families",
    }
    forged = allocation.model_copy(update={"budget": None})
    assert "future_budget_missing" in preflight(store, store.add(forged))["codes"]


def test_budget_stops_before_dispatch_at_each_pinned_limit(frozen):
    _, ref, allocation = frozen
    limits = allocation.budget
    usage = BudgetUsage(
        budget_hash=digest(limits.model_dump(mode="json")), allocation_hash=ref.content_hash
    )
    request = ReservationRequest(
        model=limits.models[0],
        configuration_hash=limits.configuration_hash,
        scenario=allocation.clusters[0].scenarios[0],
        elapsed_ms=10,
        token_ceiling=40,
        usd_ceiling=Decimal("0.02"),
        duration_ceiling_ms=100,
        retry=True,
    )
    first = reserve_future_call(allocation, usage, request, allocation_hash=ref.content_hash)
    assert first.held_tokens == 40 and first.held_usd == Decimal("0.02") and not usage.calls
    for change, reason in (
        ({"token_ceiling": None}, "ceilings"),
        ({"usd_ceiling": Decimal("0.06")}, "exceeded"),
        ({"token_ceiling": 101}, "exceeded"),
        ({"elapsed_ms": 999}, "exceeded"),
        ({"configuration_hash": "f" * 64}, "outside"),
        ({}, "exceeded"),
    ):
        with pytest.raises(ValueError, match=reason):
            reserve_future_call(
                allocation,
                first,
                request.model_copy(update=change),
                allocation_hash=ref.content_hash,
            )


def test_cluster_inference_reference_and_missing_order_bounds():
    assert two_sided_t(1, 1) == pytest.approx(0.5, abs=1e-9)
    assert two_sided_t(2.093024, 19) == pytest.approx(0.05, abs=1e-7)
    values = [[[1, 0], [1, 0]]] * 10 + [[[0, 0], [0, 0]]] * 10
    result = cluster_contrast(values + [[[1], [None]]], alpha=0.05, include_inference=True)
    assert result["complete_clusters"] == 20 and result["degrees_of_freedom"] == 19
    assert result["estimate"] == 0.25 and result["t_statistic"] == pytest.approx(19**0.5)
    assert result["standard_error"] == pytest.approx(0.25 / 19**0.5)
    assert result["confidence_interval_95"] == pytest.approx([0.13, 0.37], abs=0.001)
    assert result["sensitivity_bounds"] == pytest.approx([5 / 21, 6 / 21])


def test_contradiction_does_not_become_a_verified_difference(frozen):
    from agent_reliability_lab.research.benchmark_contracts import OUTCOMES

    _, _, allocation = frozen
    pair = allocation.clusters[0].pairs[0]
    base = dict(status="verified_failure", value=False)
    guarded = dict(status="contradictory", value=None)
    rows = {
        pair.development_slot: {
            "comparison": "verified",
            "arms": {
                arm: dict(
                    measurements=dict.fromkeys(OUTCOMES, status),
                    scoring_id=None,
                    score_revision=None,
                    evidence_hash=None,
                )
                for arm, status in (("baseline", base), ("guarded", guarded))
            },
        }
    }
    _, pairs, counts, _, _ = _measure(allocation, rows)
    assert counts == {"contradictory": 1, "missing": 1}
    assert all(p["difference"] is None for p in pairs)


@pytest.mark.integration
@pytest.mark.anyio
async def test_frozen_allocation_reconstructs_actual_pinned_evidence(tmp_path, monkeypatch):
    engine = engine_from_env()
    monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
    try:
        store = ResearchStore(engine, "test_cp14_" + uuid.uuid4().hex)
        await store.initialize()
        parent, plan = register_inputs(store, store.append)
        allocation = draft_allocation(
            store,
            plan,
            identity="cp14_study",
            count=1,
            repetitions=2,
            target=0.8,
            synthetic=True,
            budget=budget(),
        )
        allocation_ref = store.append(allocation)
        with pytest.raises(ValueError, match="consecutively"):
            store.append(allocation)
        monkeypatch.delenv("OPSDESK_PRIVATE_HELDOUT_CATALOG", raising=False)
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(plan.model_dump_json(), encoding="utf-8")
        prefix = [
            sys.executable,
            "-B",
            "-c",
            "from agent_reliability_lab.research.cli import main; main()",
            "--scope",
            store.scope,
        ]
        blocked = subprocess.run(
            [*prefix, "benchmark-preflight", str(plan_file), "--authorize-private-read"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert blocked.returncode == 2, blocked.stderr
        assert json.loads(blocked.stdout)["codes"] == [
            "allocation_missing",
            "private_catalog_unavailable",
        ]
        result_ref, scored = await benchmark.execute_benchmark(
            store, parent, allocation_ref=allocation_ref
        )
        selection = EvidenceSelection(benchmark_result=result_ref)
        report = analyze_allocation(store, allocation_ref, selection)
        primary = report["primary"]
        assert report["classification"] == "synthetic_method_validation"
        assert primary["verified_pairs"] == 2 and primary["complete_clusters"] == 1
        assert primary["p_value"] is None and primary["estimate"] == 0
        one = EvidenceSelection(
            partial_run=scored.run,
            selected_reports={
                k: v for k, v in scored.evaluator_reports.items() if k.startswith("slot_0001")
            },
        )
        partial = analyze_allocation(store, allocation_ref, one)["primary"]
        assert partial["verified_pairs"] == 1 and partial["pair_status_counts"]["missing"] == 1
        assert partial["sensitivity_bounds"] == [-0.5, 0.5]
        artifact = analysis_draft(store, allocation_ref, selection, "cp14_analysis")
        frozen_ref = store.append(artifact)
        assert verify_analysis(store, store.get(frozen_ref)) == report
        path = tmp_path / "ref.json"
        path.write_text(frozen_ref.model_dump_json(), encoding="utf-8")
        cli = [
            sys.executable,
            "-B",
            "-c",
            "from agent_reliability_lab.research.cli import main; main()",
            "--scope",
            store.scope,
            "benchmark-confirmatory-analyze",
            str(path),
        ]
        replay = subprocess.run(cli, capture_output=True, text=True, check=False)
        assert replay.returncode == 0, replay.stderr
        assert json.loads(replay.stdout) == report
        reproduce = benchmark.reproduce

        def swapped_revision(*args):
            report = reproduce(*args)
            selected = report["report_manifest"]["selected_scores"][0]
            selected["revision"] += 1
            report["selection"]["revisions"][selected["scoring_id"]] = selected["revision"]
            return report

        monkeypatch.setattr(benchmark, "reproduce", swapped_revision)
        with pytest.raises(ValueError, match="score does not pin"):
            verify_analysis(store, artifact)
    finally:
        engine.dispose()
