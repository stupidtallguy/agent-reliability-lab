"""Freeze and reconstruct confirmatory allocations, with content-free preflight."""

from collections import Counter, defaultdict
from datetime import UTC, datetime

from pydantic import ValidationError

from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.cluster_design import METHOD, plan_power
from agent_reliability_lab.research.confirmatory_contracts import (
    BudgetUsage,
    ConfirmatoryAllocation,
    PlannedCluster,
    PlannedPair,
)
from agent_reliability_lab.research.heldout import CatalogUnavailable
from agent_reliability_lab.research.heldout_design import (
    _get,
    _predecessor,
    audit_registered,
    validate_design_references,
)


def design_inputs(store, plan_ref):
    plan = _get(store, plan_ref, "benchmark_analysis_plan")
    protocol = _get(store, plan.protocol, "benchmark_confirmatory_protocol")
    validate_design_references(store, plan)
    validate_design_references(store, protocol)
    seal = _get(store, plan.catalog, "benchmark_catalog_seal")
    return plan, protocol, seal


def power_design_hash(protocol):
    return digest([METHOD, protocol.power.model_dump(mode="json")])


def _pair(protocol_ref, seed, group, scenario, ordinal, first_arm, development_slot=None):
    return PlannedPair(
        identity=digest([protocol_ref.content_hash, seed, group, scenario, ordinal, first_arm]),
        scenario=scenario,
        ordinal=ordinal,
        first_arm=first_arm,
        development_slot=development_slot,
    )


def sealed_clusters(inventory, protocol_ref, seed, count, repetitions):
    groups = defaultdict(list)
    for record in inventory:
        groups[record["cluster"]].append(record["scenario"])
    if count > len(groups):
        raise ValueError("allocation exceeds eligible template families")
    chosen = sorted(groups, key=lambda key: digest([seed, "cluster", key]))[:count]
    clusters = []
    for key in chosen:
        scenarios = sorted(groups[key], key=lambda name: digest([seed, key, name]))
        if len(scenarios) > repetitions:
            raise ValueError("too few repetitions to represent every selected family member")
        # Balance both orders within the cluster while cycling through all its scenarios.
        flip = int(digest([seed, "first-arm", key])[-1], 16) % 2
        pairs = [
            _pair(
                protocol_ref,
                seed,
                key,
                scenarios[index % len(scenarios)],
                index + 1,
                ("baseline", "guarded")[(index + flip) % 2],
            )
            for index in range(repetitions)
        ]
        clusters.append(PlannedCluster(identity=key, scenarios=scenarios, pairs=pairs))
    return clusters


def development_clusters(store, protocol, protocol_ref):
    from agent_reliability_lab.research.benchmark import schedule

    parent = _get(store, protocol.development_protocol, "benchmark_protocol")
    if parent.order_seed != protocol.order_seed:
        raise ValueError("synthetic allocation requires the same registered development seed")
    dataset = _get(store, parent.dataset, "benchmark_dataset")
    slots, _ = schedule(dataset, parent)
    groups = defaultdict(list)
    for slot in slots:
        cluster = digest([parent.dataset.content_hash, "synthetic-family", slot["template_family"]])
        scenario = slot["scenario_hash"]
        groups[cluster].append(
            _pair(
                protocol_ref,
                protocol.order_seed,
                cluster,
                scenario,
                len(groups[cluster]) + 1,
                slot["order"][0],
                slot["slot"],
            )
        )
    return [
        PlannedCluster(identity=cluster, scenarios=sorted({p.scenario for p in pairs}), pairs=pairs)
        for cluster, pairs in sorted(groups.items())
    ]


def draft_allocation(
    store,
    plan_ref,
    *,
    identity,
    count,
    repetitions,
    target,
    budget=None,
    synthetic=False,
    authorized=False,
    supersedes=None,
    version=1,
):
    plan, protocol, _ = design_inputs(store, plan_ref)
    audit_hash = None
    if synthetic:
        clusters = development_clusters(store, protocol, plan.protocol)
    else:
        if protocol.leakage.audit_version != "1.1.0":
            raise ValueError("sealed allocation requires the hardened leakage protocol")
        audit = audit_registered(
            store, plan.protocol, authorized=authorized, include_inventory=True
        )
        if not audit["passed"]:
            raise ValueError("leakage audit failed")
        audit_hash = digest(audit)
        clusters = sealed_clusters(
            audit["eligible_inventory"], plan.protocol, protocol.order_seed, count, repetitions
        )
    return ConfirmatoryAllocation(
        identity=identity,
        author=protocol.author,
        created_at=datetime.now(UTC),
        version=version,
        supersedes=supersedes,
        protocol=plan.protocol,
        plan=plan_ref,
        catalog=plan.catalog,
        source="synthetic_development" if synthetic else "sealed_held_out",
        audit_hash=audit_hash,
        power_design_hash=power_design_hash(protocol),
        seed=protocol.order_seed,
        clusters=clusters,
        cluster_count=count,
        repetitions_per_cluster=repetitions,
        planned_pairs=count * repetitions,
        target_power=target,
        budget=budget,
    )


def verify_allocation(store, allocation, *, authorized=False, audit=None):
    # Also validate objects received through in-memory adapters, including model_copy tampering.
    allocation = ConfirmatoryAllocation.model_validate_json(allocation.model_dump_json())
    _predecessor(store, allocation)
    plan, protocol, seal = design_inputs(store, allocation.plan)
    if (
        allocation.protocol != plan.protocol
        or allocation.catalog != plan.catalog
        or allocation.seed != protocol.order_seed
        or allocation.power_design_hash != power_design_hash(protocol)
    ):
        raise ValueError("allocation protocol, catalog, seed or power fingerprint differs")
    if allocation.source == "sealed_held_out":
        if protocol.leakage.audit_version != "1.1.0":
            raise ValueError("sealed allocation requires the hardened leakage protocol")
        if audit is None:
            audit = audit_registered(
                store, plan.protocol, authorized=authorized, include_inventory=True
            )
        if not audit["passed"] or digest(audit) != allocation.audit_hash:
            raise ValueError("allocation leakage audit fingerprint differs")
        expected = sealed_clusters(
            audit["eligible_inventory"],
            allocation.protocol,
            allocation.seed,
            allocation.cluster_count,
            allocation.repetitions_per_cluster,
        )
    else:
        expected = development_clusters(store, protocol, allocation.protocol)
    if allocation.clusters != expected:
        raise ValueError("frozen allocation differs from reconstructed membership or slots")
    return plan, protocol, seal


def _check_power(protocol, allocation, failures):
    design = protocol.power
    if design.planning_basis != "externally_justified" or not design.justification:
        failures.append("power_assumptions_illustrative_or_unjustified")
    if design.minimum_meaningful_difference is None or not design.minimum_effect_justification:
        failures.append("minimum_meaningful_effect_unjustified")
    if failures and any(
        code.startswith(("power_assumptions", "minimum_meaningful")) for code in failures
    ):
        return None
    power = plan_power(design)
    target = str(allocation.target_power)
    available = next(
        (
            item
            for item in power.get("feasible_designs", [])
            if item["repetitions_per_cluster"] == allocation.repetitions_per_cluster
        ),
        None,
    )
    if available is None:
        failures.append("power_schedule_mismatch")
        return None
    required = available["targets"][target]
    if required is None:
        failures.append("power_or_null_calibration_not_established")
    else:
        # Evaluate the selected grid point itself. Monte Carlo results need not be monotone.
        scenarios = [
            item for item in power["results"] if item["scenario"] in available["scenario_ids"]
        ]
        for scenario in scenarios:
            row = next(
                (
                    row
                    for row in scenario["rows"]
                    if row["planned_clusters"] == allocation.cluster_count
                ),
                None,
            )
            if (
                row is None
                or not row["null_calibrated"]
                or row["power_monte_carlo_interval"][0] < allocation.target_power
            ):
                failures.append("selected_allocation_fails_power_or_null_calibration")
                break
    return required


def preflight(store, allocation_ref, *, authorized=False):
    failures = []
    plan_only = allocation_ref.kind == "benchmark_analysis_plan"
    report = dict(
        preflight_version="1.0.0",
        allocation=None if plan_only else allocation_ref.model_dump(mode="json"),
        execution_enabled=False,
        semantic_independence="not_established",
        human_review="not_performed",
    )
    try:
        allocation = None if plan_only else _get(store, allocation_ref, "benchmark_allocation")
        plan_ref = allocation_ref if plan_only else allocation.plan
        plan, protocol, seal = design_inputs(store, plan_ref)
    except (ValueError, ValidationError):
        return dict(**report, status="blocked", codes=["allocation_or_analysis_plan_unverified"])
    report.update(
        benchmark_version=seal.benchmark_version, analysis_plan=plan_ref.model_dump(mode="json")
    )
    if allocation is not None:
        report.update(
            planned_clusters=allocation.cluster_count,
            repetitions_per_cluster=allocation.repetitions_per_cluster,
            planned_pairs=allocation.planned_pairs,
            target_power=allocation.target_power,
            audit_fingerprint=allocation.audit_hash,
            power_design_fingerprint=allocation.power_design_hash,
        )
    audit = None
    if not authorized:
        failures.append("private_catalog_authorization_required")
    else:
        try:
            audit = audit_registered(store, plan.protocol, authorized=True, include_inventory=True)
        except CatalogUnavailable:
            failures.append("private_catalog_unavailable")
        except (ValueError, ValidationError):
            failures.append("private_catalog_or_comparison_unverified")
    if audit is not None:
        report.update(
            eligible_template_families=audit["eligible_template_families"],
            provenance=audit["private_origin_counts"],
            provenance_assurance="declared",
        )
        if not audit["passed"]:
            failures.append("leakage_audit_failed")
        if set(audit["private_origin_counts"]) != {"private_authored"}:
            failures.append("confirmatory_provenance_ineligible")
        if (
            allocation is not None
            and audit["eligible_template_families"] < allocation.cluster_count
        ):
            failures.append("insufficient_eligible_template_families")
    if allocation is None:
        return dict(**report, status="blocked", codes=["allocation_missing", *failures])
    if allocation.source != "sealed_held_out":
        failures.append("synthetic_allocation_ineligible")
    if audit is not None or allocation.source == "synthetic_development":
        try:
            verify_allocation(store, allocation, audit=audit)
        except (ValueError, ValidationError):
            failures.append("allocation_integrity_failure")
    required = _check_power(protocol, allocation, failures)
    report["conditional_required_clusters"] = required
    if (
        required is not None
        and audit is not None
        and audit["eligible_template_families"] < required
    ):
        if "insufficient_eligible_template_families" not in failures:
            failures.append("insufficient_eligible_template_families")
    scenarios = Counter(p.scenario for cluster in allocation.clusters for p in cluster.pairs)
    if allocation.budget is None:
        failures.append("future_budget_missing")
    elif (
        allocation.budget.max_model_calls < 2 * allocation.planned_pairs
        or allocation.budget.max_calls_per_scenario < 2 * max(scenarios.values())
    ):
        failures.append("future_budget_cannot_cover_planned_arms")
    return dict(
        **report,
        status="blocked" if failures else "structurally_ready_execution_disabled",
        codes=failures,
    )


def reserve_future_call(allocation, usage, request, *, allocation_hash):
    """Pure admission check for a future transactional broker. No dispatch path."""
    budget = allocation.budget
    if budget is None or usage.budget_hash != digest(budget.model_dump(mode="json")):
        raise ValueError("future budget is missing or differs from the ledger")
    if (
        allocation_hash != digest(allocation.model_dump(mode="json"))
        or usage.allocation_hash != allocation_hash
    ):
        raise ValueError("budget ledger allocation differs")
    allowed = {pair.scenario for cluster in allocation.clusters for pair in cluster.pairs}
    if (
        request.model not in budget.models
        or request.configuration_hash != budget.configuration_hash
        or request.scenario not in allowed
        or set(usage.calls) - allowed
        or set(usage.retries) - allowed
    ):
        raise ValueError("model, configuration or scenario is outside the frozen authorization")
    if any(
        value is None
        for value in (request.token_ceiling, request.usd_ceiling, request.duration_ceiling_ms)
    ):
        raise ValueError("trusted reservation ceilings are required")
    if request.elapsed_ms < usage.duration_ms:
        raise ValueError("budget clock cannot move backwards")
    calls = dict(usage.calls)
    retries = dict(usage.retries)
    calls[request.scenario] = calls.get(request.scenario, 0) + 1
    if request.retry:
        retries[request.scenario] = retries.get(request.scenario, 0) + 1
    tokens = usage.held_tokens + request.token_ceiling
    cost = usage.held_usd + request.usd_ceiling
    if (
        sum(calls.values()) > budget.max_model_calls
        or max(calls.values()) > budget.max_calls_per_scenario
        or max(retries.values(), default=0) > budget.max_retries_per_scenario
        or tokens > budget.max_total_tokens
        or cost > budget.max_cost_usd
        or request.elapsed_ms + request.duration_ceiling_ms > budget.max_duration_ms
    ):
        raise ValueError("future execution budget would be exceeded")
    return BudgetUsage(
        budget_hash=usage.budget_hash,
        allocation_hash=allocation_hash,
        duration_ms=request.elapsed_ms,
        held_tokens=tokens,
        held_usd=cost,
        calls=calls,
        retries=retries,
    )
