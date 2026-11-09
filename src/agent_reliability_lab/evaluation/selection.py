"""Explicit scoring-revision selection; incompatible semantics never pool."""

from dataclasses import dataclass

from agent_reliability_lab.evaluation.contracts import EvaluationResult


class IncompatibleCohort(ValueError):
    code = "incompatible_scoring_cohort"


def requested_version(result):
    return result.scoring_provenance.get("requested_evaluator_version", result.evaluator_version)


def semantic_version(result):
    if result.scoring_provenance.get(
        "effective_evaluator_version"
    ) is None and result.scoring_provenance.get("experimental_context_required"):
        return requested_version(result)
    return result.evaluator_version


def compatible(results):
    if len({semantic_version(r) for r in results}) > 1:
        raise IncompatibleCohort("Select one evaluator version; use separate comparison reports.")
    for field in (
        "evaluator_source_hash",
        "adversarial_source_hash",
        "scoring_implementation_hash",
    ):
        hashes = {
            r.scoring_provenance.get(field) for r in results if r.scoring_provenance.get(field)
        }
        if len(hashes) > 1:
            raise IncompatibleCohort(
                "Evaluator implementation hashes differ; select compatible revisions."
            )


@dataclass(frozen=True)
class Cohort:
    results: list[EvaluationResult]
    revisions: dict[str, int]
    unavailable: list[dict]
    version: str


def select(store, experiment, trials, *, evaluator_version=None, scoring_ids=None, trial_ids=None):
    from agent_reliability_lab.evaluation.versions import validate_selection

    if evaluator_version and evaluator_version != "1.0.1":
        validate_selection(evaluator_version)
    results, revisions, unavailable = [], {}, []
    wanted = set(scoring_ids or [])
    trial_filter = set(trial_ids) if trial_ids is not None else None
    found = set()
    for trial in trials:
        if trial_filter is not None and trial["trial_id"] not in trial_filter:
            continue
        choices = []
        for revision, result in enumerate(store.scores(trial["trial_id"]), 1):
            if wanted and result.scoring_id not in wanted:
                continue
            if evaluator_version and semantic_version(result) != evaluator_version:
                continue
            choices.append((revision, result))
        if not choices:
            unavailable.append(
                dict(trial_id=trial["trial_id"], reason="no_compatible_scoring_revision")
            )
            continue
        if wanted and len(choices) > 1:
            raise IncompatibleCohort("Select at most one revision per trial.")
        revision, result = choices[-1]
        results.append(result)
        revisions[result.scoring_id] = revision
        found.add(result.scoring_id)
    if wanted - found:
        raise IncompatibleCohort(
            "Requested scoring IDs are unavailable in this experiment/version."
        )
    if trial_filter is not None and trial_filter - {t["trial_id"] for t in trials}:
        raise IncompatibleCohort("Requested trial is outside the experiment.")
    compatible(results)
    version = (
        semantic_version(results[0])
        if results
        else evaluator_version
        or experiment["manifest"]["config"].get("experimental_evaluator", "1.1.0")
    )
    return Cohort(results, revisions, unavailable, version)
