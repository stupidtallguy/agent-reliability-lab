from datetime import UTC, datetime

from agent_reliability_lab.evaluation.contracts import OracleSpec
from agent_reliability_lab.research.contracts import Attestation, Oracle, Reviewer


def common(identity, author="synthetic_author", version=1):
    return dict(identity=identity, author=author, version=version, created_at=datetime.now(UTC))


def oracle():
    return Oracle(
        **common("synthetic_oracle"),
        scenario_id="normal_order",
        scenario_version=1,
        scenario_hash="a" * 64,
        legitimate_behavior="Read the synthetic order status.",
        prohibited_behavior="Do not mutate records.",
        state_assertions=[],
        response_assertions=[],
        trace_assertions=[],
        attack_objective=None,
        evidence_requirements=["frozen_state"],
        metric_eligibility={"task_success": True},
        scoring_rules=OracleSpec(),
    )


def reviewer(name, role="reviewer"):
    return Reviewer(
        **common(name, name),
        display_name="Synthetic test identity " + name,
        role=role,
        conflict_of_interest="Synthetic fixture only; no human review.",
    )


def attestation(store, oracle_ref, who, decision="approve", version=1):
    return Attestation(
        **common("review_" + who.identity, who.identity, version),
        oracle=oracle_ref,
        reviewer=store.reference(who),
        decision=decision,
        disagreement_class="none" if decision == "approve" else "material",
        rationale="Synthetic workflow test, not a human attestation.",
        evidence_references=["synthetic_fixture"],
        no_conflict_declared=True,
        origin="synthetic_test",
    )
