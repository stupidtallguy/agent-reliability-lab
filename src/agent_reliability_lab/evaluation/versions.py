"""Explicit selection errors and error-result identity, without legacy rule changes."""

import hashlib
from pathlib import Path

from agent_reliability_lab.evaluation.contracts import EvaluationResult, Evidence
from agent_reliability_lab.opsdesk.fixtures import digest

EXPERIMENTAL_VERSIONS = frozenset({"1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0"})


class UnsupportedEvaluatorVersion(ValueError):
    code = "unsupported_evaluator_version"


def validate_selection(version: str) -> None:
    if version not in EXPERIMENTAL_VERSIONS:
        raise UnsupportedEvaluatorVersion("Unsupported experimental evaluator version.")


def implementation_identity(
    package: Path | None = None, lockfile: Path | None = None, *, packaged_lock: bool = False
) -> dict:
    """Source snapshot, including shared helpers; not executed-code attestation."""
    package = package or Path(__file__).parents[1]
    lockfile = lockfile or Path("uv.lock")
    if packaged_lock and not lockfile.is_file():
        lockfile = package / "resources/uv.lock"
    files = {
        p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(package.rglob("*.py"))
    }
    if not files:
        raise ValueError("scoring source identity unavailable")
    dependency_hash = (
        hashlib.sha256(lockfile.read_bytes()).hexdigest() if lockfile.is_file() else None
    )
    return dict(
        implementation_scope="package_python_and_available_lockfile_v1",
        scoring_implementation_hash=digest(dict(files=files, lock=dependency_hash)),
        dependency_lock_hash=dependency_hash,
    )


def version_provenance(result, selected, effective=None, error=None):
    """Do not confuse a retained legacy label with an actually invoked scorer."""
    result.scoring_provenance.update(
        requested_evaluator_version=selected,
        effective_evaluator_version=effective,
        result_classification="error" if error else "scored" if effective else "excluded",
        error_classification=error,
    )
    result.scoring_provenance.setdefault(
        "required_context",
        "experimental_capture"
        if selected in {"1.4.0", "1.5.0", "1.6.0", "1.7.0"}
        else "when_experimental_plan_configured",
    )
    result.scoring_provenance.setdefault("context_reconstructed", False)
    result.scoring_provenance.setdefault("context_provenance", None)
    if selected in {"1.4.0", "1.5.0", "1.6.0", "1.7.0"}:
        result.evaluator_version = selected
    if selected in {"1.5.0", "1.6.0", "1.7.0"}:
        result.scoring_provenance.update(implementation_identity(packaged_lock=selected == "1.7.0"))
    return result


def error_identity(result: EvaluationResult, evidence: Evidence, selected: str) -> EvaluationResult:
    """Preserve old defaults; repair requested modern error labels before returning."""
    if evidence.experimental is not None and selected in {"1.2.0", "1.3.0"}:
        result.evaluator_version = selected
        result.evidence_reference = f"opsdesk-eval://trials/{result.trial_id}/evidence"
        root = Path(__file__).parents[1] / "adversarial"
        result.scoring_provenance.update(
            requested_experimental_evaluator=selected,
            attack_attribution="decision_origin_v2"
            if selected == "1.3.0"
            else "decision_origin_v1",
            adversarial_source_hash=digest(
                {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(root.glob("*.py"))
                }
            ),
        )
    return result
