"""Reconstruct confirmatory arithmetic from allocated, revision-pinned comparisons."""

import platform
from collections import Counter
from datetime import UTC, datetime

from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import build_result, verify_result
from agent_reliability_lab.research.benchmark_contracts import OUTCOMES
from agent_reliability_lab.research.cluster_design import cluster_contrast
from agent_reliability_lab.research.confirmatory import verify_allocation
from agent_reliability_lab.research.confirmatory_contracts import ConfirmatoryAnalysis
from agent_reliability_lab.research.heldout_design import _get, _predecessor

ARMS = ("baseline", "guarded")
VERIFIED = {"verified_success": True, "verified_failure": False}


def _classify(row, arm, metric):
    if row is None or arm not in row["arms"]:
        return "missing", None
    observed = row["arms"][arm]["measurements"][metric]
    status = observed["status"]
    value = observed["value"]
    if status in VERIFIED and value is not VERIFIED[status]:
        raise ValueError("verified measurement contradicts its status")
    return status, value


def _difference(row, outcomes):
    if (
        row is not None
        and row["comparison"] == "verified"
        and all(status in VERIFIED for status, _ in outcomes)
    ):
        return int(outcomes[1][1]) - int(outcomes[0][1])
    return None


def _pair_status(row, outcomes, difference):
    if difference is not None:
        return "verified"
    statuses = {status for status, _ in outcomes}
    if "contradictory" in statuses:
        return "contradictory"
    if row is not None and row["comparison"] == "excluded":
        return "excluded"
    for status in ("missing", "unavailable", "unresolved", "not_applicable"):
        if status in statuses:
            return status
    return "unresolved"


def _measure(allocation, rows):
    cluster_differences, pairs, primary_counts = [], [], Counter()
    arm_counts = {arm: Counter() for arm in ARMS}
    secondary = {
        metric: {
            "complete_pairs": 0,
            "joint_positive": dict.fromkeys(ARMS, 0),
            **{arm: Counter() for arm in ARMS},
        }
        for metric in OUTCOMES[1:]
    }
    for cluster in allocation.clusters:
        order_values = {arm: [] for arm in ARMS}
        for pair in cluster.pairs:
            row = rows.get(pair.development_slot)
            observed = [_classify(row, arm, "task_success") for arm in ARMS]
            for arm, (status, _) in zip(ARMS, observed, strict=True):
                arm_counts[arm][status] += 1
            difference = _difference(row, observed)
            status = _pair_status(row, observed, difference)
            primary_counts[status] += 1
            order_values[pair.first_arm].append(difference)
            pairs.append(
                dict(
                    pair=pair.identity,
                    cluster=cluster.identity,
                    first_arm=pair.first_arm,
                    status=status,
                    difference=difference,
                    arms={
                        arm: dict(
                            status=observed[index][0],
                            scoring_id=row["arms"][arm]["scoring_id"]
                            if row is not None and arm in row["arms"]
                            else None,
                            score_revision=row["arms"][arm]["score_revision"]
                            if row is not None and arm in row["arms"]
                            else None,
                            evidence_hash=row["arms"][arm]["evidence_hash"]
                            if row is not None and arm in row["arms"]
                            else None,
                        )
                        for index, arm in enumerate(ARMS)
                    },
                )
            )
            for metric, counts in secondary.items():
                outcomes = [_classify(row, arm, metric) for arm in ARMS]
                if _difference(row, outcomes) is not None:
                    counts["complete_pairs"] += 1
                    for arm, (_, value) in zip(ARMS, outcomes, strict=True):
                        counts["joint_positive"][arm] += value
                for arm, (state, _) in zip(ARMS, outcomes, strict=True):
                    counts[arm][state] += 1
        cluster_differences.append(list(order_values.values()))
    return cluster_differences, pairs, dict(primary_counts), arm_counts, secondary


def analyze_allocation(store, allocation_ref, selection, *, authorized=False):
    allocation = _get(store, allocation_ref, "benchmark_allocation")
    plan, _, _ = verify_allocation(store, allocation, authorized=authorized)
    result = None
    evidence_hash = None
    if selection.benchmark_result or selection.partial_run:
        if allocation.source != "synthetic_development":
            raise ValueError("CP14 has no authorized held-out execution evidence source")
        if selection.benchmark_result:
            artifact = _get(store, selection.benchmark_result, "benchmark_result")
            run_ref = artifact.run
            evidence_hash = artifact.result_hash
        else:
            run_ref = selection.partial_run
        run = _get(store, run_ref, "benchmark_run")
        if run.allocation != allocation_ref:
            raise ValueError("evidence run was not frozen against this allocation")
        if selection.benchmark_result:
            result = verify_result(store, artifact)
        else:
            result = build_result(store, run_ref, selection.selected_reports, partial=True)
            evidence_hash = digest(result)
    rows = {row["slot"]: row for row in result["pairs"]} if result else {}
    differences, pairs, counts, arms, secondary = _measure(allocation, rows)
    primary = cluster_contrast(differences, alpha=plan.alpha, include_inference=True)
    classification = (
        "synthetic_method_validation"
        if allocation.source == "synthetic_development"
        else "held_out_evidence_unavailable"
    )
    return dict(
        analysis_version="1.0.0",
        registered_method=plan.paired_method,
        python_version=plan.python_version,
        classification=classification,
        confirmatory_eligible=False,
        execution_enabled=False,
        allocation=allocation_ref.model_dump(mode="json"),
        protocol=allocation.protocol.model_dump(mode="json"),
        analysis_plan=allocation.plan.model_dump(mode="json"),
        evidence_selection=selection.model_dump(mode="json"),
        verified_evidence_hash=evidence_hash,
        order_seed=allocation.seed,
        simulation_seed=plan.simulation_seed,
        alpha=plan.alpha,
        primary=dict(
            **primary,
            planned_pairs=allocation.planned_pairs,
            verified_pairs=counts.get("verified", 0),
            pair_status_counts=counts,
            arm_status_counts=arms,
            inference_status="synthetic_arithmetic_only"
            if primary["p_value"] is not None
            else "unavailable",
        ),
        secondary=secondary,
        secondary_inference="descriptive_only",
        pairs=pairs,
    )


def analysis_draft(store, allocation_ref, selection, identity, *, authorized=False):
    allocation = _get(store, allocation_ref, "benchmark_allocation")
    report = analyze_allocation(store, allocation_ref, selection, authorized=authorized)
    return ConfirmatoryAnalysis(
        identity=identity,
        author=allocation.author,
        created_at=datetime.now(UTC),
        allocation=allocation_ref,
        evidence=selection,
        producer_python_version=platform.python_version(),
        report=report,
        result_hash=digest(report),
    )


def verify_analysis(store, artifact, *, authorized=False):
    _predecessor(store, artifact)
    report = analyze_allocation(
        store, artifact.allocation, artifact.evidence, authorized=authorized
    )
    if report != artifact.report or digest(report) != artifact.result_hash:
        raise ValueError("confirmatory analysis differs from reconstructed evidence")
    return report
