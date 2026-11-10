"""Version-aware comparison identity; absent is never equal to present."""

import re

from agent_reliability_lab.evaluation.selection import compatible


class UnverifiableImplementation(ValueError):
    code = "unverifiable_implementation_identity"


def identity_status(result):
    provenance = result.scoring_provenance
    version = provenance.get("requested_evaluator_version", result.evaluator_version)
    required = {"evaluator_source_hash"}
    effective = provenance.get("effective_evaluator_version", result.evaluator_version)
    if effective in {"1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0"}:
        required.add("adversarial_source_hash")
    if version in {"1.5.0", "1.6.0", "1.7.0"}:
        required |= {"scoring_implementation_hash", "dependency_lock_hash", "implementation_scope"}
    missing = sorted(k for k in required if not provenance.get(k))
    invalid = sorted(
        k
        for k in required
        if k.endswith("_hash")
        and provenance.get(k)
        and (not isinstance(provenance[k], str) or not re.fullmatch(r"[a-f0-9]{64}", provenance[k]))
    )
    if "implementation_scope" in required and provenance.get("implementation_scope") not in (
        None,
        "package_python_and_available_lockfile_v1",
    ):
        invalid.append("implementation_scope")
    return dict(
        invalid=invalid,
        version=version,
        status="historically_unavailable"
        if missing and version != "1.7.0"
        else "missing"
        if missing
        else "matching_evidence_available",
        required=sorted(required),
        missing=missing,
        not_required=sorted(
            {
                "adversarial_source_hash",
                "scoring_implementation_hash",
                "dependency_lock_hash",
                "implementation_scope",
            }
            - required
        ),
    )


def require_compatible(results):
    compatible(results)
    statuses = [identity_status(r) for r in results]
    if any(s["missing"] or s["invalid"] for s in statuses):
        raise UnverifiableImplementation("Required scoring implementation identity is unavailable.")
    if (
        len(
            {
                r.scoring_provenance.get("dependency_lock_hash")
                for r in results
                if r.scoring_provenance.get("dependency_lock_hash")
            }
        )
        > 1
    ):
        raise UnverifiableImplementation("Dependency identities differ.")
    return statuses
