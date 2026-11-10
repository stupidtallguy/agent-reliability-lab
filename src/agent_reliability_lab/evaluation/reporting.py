"""Version dispatch; historical renderer implementations remain frozen."""

from agent_reliability_lab.evaluation import reporting_legacy as legacy
from agent_reliability_lab.evaluation import reporting_v170 as candidate
from agent_reliability_lab.evaluation.manifests import ManifestError, validate_manifest

RENDERER_VERSION = legacy.RENDERER_VERSION
CANDIDATE_RENDERER_VERSION = legacy.CANDIDATE_RENDERER_VERSION
DEFINITIONS = legacy.DEFINITIONS
content_hash = legacy.content_hash


def report(store, experiment_id, **options):
    version = options.get("evaluator_version")
    experiment = store.experiment(experiment_id)
    try:
        _, config = validate_manifest(experiment)
    except ManifestError:
        if version == "1.7.0":
            return candidate.report(store, experiment_id, **options)
        raise
    trials = store.list_trials(experiment_id=experiment_id)
    from agent_reliability_lab.evaluation.selection import select

    cohort = select(store, experiment, trials, **options)
    if version == "1.7.0" or cohort.version == "1.7.0":
        return candidate.report(store, experiment_id, **options)
    return legacy.report(store, experiment_id, **options)


def reproduce(store, report_id):
    _, record, _ = store.saved_report(report_id)
    if record and record["manifest"]["renderer_version"] == "2.2.0":
        return candidate.reproduce(store, report_id)
    return legacy.reproduce(store, report_id)


def markdown(document):
    return (
        candidate.markdown(document)
        if document.get("renderer_version") == "2.2.0"
        else legacy.markdown(document)
    )


def export(document, *args, **kwargs):
    return (candidate.export if document.get("renderer_version") == "2.2.0" else legacy.export)(
        document, *args, **kwargs
    )
