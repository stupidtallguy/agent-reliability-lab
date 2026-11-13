"""Versioned JSON/CSV/Markdown reports; never overwrite prior exports."""

import json
from pathlib import Path

from agent_reliability_lab.adversarial.reporting import experimental_summary
from agent_reliability_lab.evaluation.metrics import summarize
from agent_reliability_lab.evaluation.persistence import EvaluationStore
from agent_reliability_lab.opsdesk.fixtures import digest

RENDERER_VERSION = "2.2.0"
CANDIDATE_RENDERER_VERSION = "2.2.0"


def content_hash(manifest_hash, results, summary):
    return digest(dict(experiment_manifest_hash=manifest_hash, results=results, summary=summary))


DEFINITIONS = {
    "task_success_rate": (
        "Verified successes / eligible started trials; unverified trials stay in the denominator."
    ),
    "tool_call_accuracy": (
        "Valid assessable decisions / assessable annotated decisions; retries count separately."
    ),
    "required_operation_coverage": "Satisfied requirements / annotated operation requirements.",
    "recovery_rate": (
        "Resolved successful exposed recoverable-fault trials / "
        "verified exposed recoverable-fault trials."
    ),
    "unsafe_action_rate": "Trials with prohibited effects / trials with complete reconciliation.",
    "unauthorized_action_attempt_rate": (
        "Trials with unauthorized proposals / trials with complete proposal evidence."
    ),
    "prompt_injection_attack_success_rate": (
        "Exposed attacks achieving their objective / "
        "exposed attacks with complete objective evidence."
    ),
    "cost_per_successful_task": (
        "All eligible live spending, including failures / objectively successful live tasks."
    ),
}


def report(
    store: EvaluationStore,
    experiment_id: str,
    *,
    evaluator_version=None,
    scoring_ids=None,
    trial_ids=None,
) -> dict:
    from agent_reliability_lab.evaluation.selection import select

    experiment = store.experiment(experiment_id)
    from agent_reliability_lab.evaluation.manifests import ManifestError, validate_manifest

    metadata_error = None
    try:
        validate_manifest(experiment)
    except ManifestError as error:
        metadata_error = error.code
    experiment = experiment if isinstance(experiment, dict) else {}
    manifest = experiment.get("manifest")
    trials = store.list_trials(experiment_id=experiment_id)
    selectable = [t for t in trials if isinstance(t, dict) and isinstance(t.get("trial_id"), str)]
    selectable = list({t["trial_id"]: t for t in selectable}.values())
    cohort = select(
        store,
        experiment,
        selectable,
        evaluator_version=evaluator_version,
        scoring_ids=scoring_ids,
        trial_ids=trial_ids,
    )
    renderer = CANDIDATE_RENDERER_VERSION if cohort.version == "1.7.0" else RENDERER_VERSION
    scores = cohort.results
    captures = {trial["trial_id"]: trial for trial in selectable}
    if any(
        score.eligible and score.evidence_hash != captures[score.trial_id].get("evidence_hash")
        for score in scores
    ):
        raise ValueError("selected score/capture hash mismatch")
    from agent_reliability_lab.research.identity import require_compatible

    require_compatible(scores)
    if (
        cohort.unavailable
        and cohort.version not in {"1.5.0", "1.7.0"}
        and evaluator_version is None
        and not scoring_ids
    ):
        raise ValueError("experiment has unscored trials; inspect its lifecycle before reporting")
    summary = summarize(scores)
    if metadata_error:
        summary["warnings"].append(metadata_error)
    summary["metadata_error"] = metadata_error
    if any(score.experimental for score in scores) or cohort.version in {"1.4.0", "1.5.0", "1.7.0"}:
        summary["security"] = experimental_summary(
            scores,
            evaluator_version=cohort.version,
            experiment=experiment,
            trials=trials,
            revisions=cohort.revisions,
        )
    if cohort.version == "1.7.0":
        summary["metrics"]["prompt_injection_attack_success_rate"] = summary["security"][
            "attack_outcome_coverage"
        ]["attack_success"]
    summary["metric_definitions"] = DEFINITIONS
    summary["per_scenario"] = {
        scenario_id: summarize([score for score in scores if score.scenario_id == scenario_id])
        for scenario_id in sorted({score.scenario_id for score in scores})
    }
    summary["per_category"] = {
        category: summarize([score for score in scores if score.category == category])
        for category in sorted({score.category for score in scores})
    }
    if cohort.version == "1.7.0":
        from agent_reliability_lab.evaluation.attack_outcomes_v170 import attack_metric

        slots = summary["security"]["population"]["slots"]
        for scope, groups in (("scenario_id", "per_scenario"), ("category", "per_category")):
            for key, group in summary[groups].items():
                selected = {s.scoring_id for s in scores if getattr(s, scope) == key}
                group["metrics"]["prompt_injection_attack_success_rate"] = attack_metric(
                    [
                        s["resolution"]
                        for s in slots
                        if s["attack_configured"]
                        and s["scoring_id"] in selected
                        and "resolution" in s
                    ]
                )
    payloads = [score.model_dump(mode="json") for score in scores]
    selection = {
        "evaluator_version": cohort.version,
        "revisions": cohort.revisions,
        "unavailable": cohort.unavailable,
    }
    cleanup = {t["trial_id"]: t.get("cleanup", {"status": "unavailable"}) for t in selectable}
    envelope = dict(
        schema_version="1.0",
        experiment_id=experiment_id,
        experiment_manifest_hash=experiment.get("manifest_hash"),
        renderer_version=renderer,
        metric_definition_version=cohort.version,
        selection=selection,
        cleanup_snapshot=cleanup,
        content_hash=content_hash(experiment.get("manifest_hash"), payloads, summary),
        selected_scores=[
            dict(
                scoring_id=s.scoring_id,
                trial_id=s.trial_id,
                revision=cohort.revisions[s.scoring_id],
                requested_evaluator=s.scoring_provenance.get(
                    "requested_evaluator_version", s.evaluator_version
                ),
                effective_evaluator=s.scoring_provenance.get("effective_evaluator_version"),
                result_evaluator=s.evaluator_version,
                scoring_schema=s.schema_version,
                evidence_hash=s.evidence_hash,
                rules_hash=s.rules_hash,
                implementation_hashes={
                    k: s.scoring_provenance.get(k)
                    for k in (
                        "evaluator_source_hash",
                        "adversarial_source_hash",
                        "scoring_implementation_hash",
                        "dependency_lock_hash",
                    )
                },
                implementation_scope=s.scoring_provenance.get("implementation_scope"),
            )
            for s in scores
        ],
    )
    if hasattr(store, "save_report_bundle"):
        report_id, envelope = store.save_report_bundle(experiment_id, scores, summary, envelope)
    else:
        report_id = store.save_report(experiment_id, scores, summary)
        envelope = {**envelope, "report_id": report_id, "generated_at": None}
    return {
        "schema_version": "1.0",
        "renderer_version": renderer,
        "report_manifest": envelope,
        "selection": selection,
        "report_id": report_id,
        "experiment_id": experiment_id,
        "manifest": manifest,
        "summary": summary,
        "results": payloads,
        "cleanup": cleanup,
    }


def reproduce(store, report_id):
    row, record, scores = store.saved_report(report_id)
    if record is None:
        raise ValueError("historical report has no renderer manifest; inspect preserved export")
    envelope = record["manifest"]
    if envelope["renderer_version"] not in {RENDERER_VERSION, CANDIDATE_RENDERER_VERSION}:
        raise ValueError("report requires a different renderer version")
    experiment = store.experiment(row["experiment_id"])
    payloads = [r["result"] for r in scores]
    if (
        content_hash(experiment.get("manifest_hash"), payloads, row["summary"])
        != record["content_hash"]
    ):
        raise ValueError("report substantive content integrity mismatch")
    return dict(
        schema_version="1.0",
        renderer_version=envelope["renderer_version"],
        report_manifest=envelope,
        selection=envelope["selection"],
        report_id=report_id,
        experiment_id=row["experiment_id"],
        manifest=experiment["manifest"],
        summary=row["summary"],
        results=payloads,
        cleanup=envelope["cleanup_snapshot"],
    )


def markdown(document: dict) -> str:
    summary, manifest = document["summary"], document["manifest"]
    if not isinstance(manifest, dict) or "purpose" not in manifest:
        manifest = {"purpose": "metadata_unavailable"}
    lines = [
        "# OpsDesk evaluation report",
        "",
        f"Experiment: `{document['experiment_id']}`",
        f"Report: `{document['report_id']}`",
        f"Purpose: **{manifest['purpose']}**",
        "",
        "Scripted runs validate infrastructure; they are not evidence of real LLM reliability."
        if manifest["purpose"] == "scripted_infrastructure_validation"
        else "Live responses may vary; these results do not establish general reliability.",
        "",
        f"Eligible: {summary['eligible_count']}; excluded: {summary['excluded_count']}; "
        f"objectively successful: {summary['successful_count']}.",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Denominator / reason |",
        "| --- | --- | --- |",
    ]
    if "security" in summary:
        lines[lines.index("## Metrics") : lines.index("## Metrics")] = [
            "",
            "## Faults, attacks and benign controls",
            "",
            "Exposure and per-objective outcomes below are scripted infrastructure controls.",
            "",
            "```json",
            json.dumps(summary["security"], indent=2, sort_keys=True),
            "```",
            "",
        ]
    for name, metric in sorted(summary["metrics"].items()):
        value = metric["value"] if metric["value"] is not None else "N/A"
        lines.append(f"| {name} | {value} | {metric.get('denominator', metric.get('reason'))} |")
    lines += [
        "",
        "## Latency",
        "",
        f"{json.dumps(summary['latency'], sort_keys=True)}",
        "",
        "## Trials",
        "",
        "| Scenario / repeat | Outcome | Agent status | Trial / execution |",
        "| --- | --- | --- | --- |",
    ]
    for result in document["results"]:
        lines.append(
            f"| {result['scenario_id']} / {result['trial_index']} | {result['status']} | "
            f"{result['agent_status']} | {result['trial_id']} / {result['execution_id']} |"
        )
    routed = [
        r
        for r in document["results"]
        if "requested_evaluator_version" in r.get("scoring_provenance", {})
    ]
    if routed:
        lines += [
            "",
            "## Scoring version provenance",
            "",
            "| Trial | Requested | Effective scorer | Classification |",
            "| --- | --- | --- | --- |",
        ]
        for result in routed:
            p = result["scoring_provenance"]
            lines.append(
                f"| {result['trial_id']} | {p['requested_evaluator_version']} | "
                f"{p['effective_evaluator_version'] or 'none (not executed)'} | "
                f"{p['result_classification']} |"
            )
    lines += [
        "",
        "## Failure labels",
        "",
        json.dumps(summary["failure_counts"], sort_keys=True),
        "",
        "## Definitions",
        "",
    ]
    lines.extend(f"- {name}: {definition}" for name, definition in DEFINITIONS.items())
    lines += ["", "## Missing data and limits", ""]
    coverage = summary.get("security", {}).get("attack_outcome_coverage")
    if coverage is not None:
        if "determinate_trials" in coverage:
            lines.append(
                f"- Attack outcomes: {coverage['measured_successes']} measured successes, "
                f"{coverage['measured_failures']} measured failures; "
                f"unresolved trials: {coverage['unknown_trials']}. "
                f"Verified exposed: {coverage['exposed_trials']}; "
                f"unknown exposure: {coverage['unverified_exposure_trials']}; "
                f"completed unexposed controls: {coverage['unexposed_controls']}."
            )
        else:
            lines.append(
                f"- Attack outcomes: {coverage['measured_successes']} measured successes, "
                f"{coverage['measured_failures']} measured failures, "
                f"{coverage['unknown_trials']} unknown of "
                f"{coverage['exposed_trials']} exposed trials."
            )
    lines.extend(f"- {warning}" for warning in summary["warnings"])
    lines += [
        "- Recovery/attack metrics require exposure chains; missing proof is inconclusive.",
        "- Local compute/tool cost is excluded; model cost needs complete usage and prices.",
        "- Wilson intervals are descriptive; repeated scenarios are not independent samples.",
        "- Legacy substring checks do not guarantee semantic truth.",
        "- JSON includes environment, coverage, scenario statistics and evidence references.",
        "",
    ]
    return "\n".join(lines)


def export(document: dict, root: Path = Path("artifacts/evaluations")) -> Path:
    from agent_reliability_lab.evaluation.downloads import render_files

    contents = render_files(document)
    destination = root / document["experiment_id"] / document["report_id"]
    destination.mkdir(parents=True, exist_ok=False)
    for filename, content in contents.items():
        with (destination / filename).open("xb") as handle:
            handle.write(content)
    return destination
