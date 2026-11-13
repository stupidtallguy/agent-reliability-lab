"""Pure report serialization for downloads; no filesystem or database writes."""

import csv
import io
import json

from agent_reliability_lab.evaluation.reporting import markdown

ATTACK_COUNTS = (
    "configured_attack_trials",
    "exposed_trials",
    "unexposed_controls",
    "determinate_trials",
    "unknown_trials",
    "unverified_exposure_trials",
    "measured_successes",
    "measured_failures",
    "unsupported_trials",
    "trial_metadata_unavailable",
)
POPULATION_COUNTS = (
    "planned_trials",
    "materialized_trials",
    "selected_scores",
    "unmaterialized_trials",
    "unscored_trials",
    "completed_trials",
    "eligible_trials",
    "excluded_trials",
)


def render_files(document: dict) -> dict[str, bytes]:
    candidate = document.get("renderer_version") == "2.2.0"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "scenario_id",
            "metric",
            "value",
            "numerator",
            "denominator",
            "status",
            "reason",
            "units",
        ],
    )
    writer.writeheader()
    by_scenario = document["summary"]["per_scenario"]
    if candidate:
        by_scenario = dict(sorted(by_scenario.items()))
    groups = {"__all__": document["summary"], **by_scenario}
    for scope, summary in groups.items():
        for name, record in sorted(summary["metrics"].items()):
            row = {key: record.get(key) for key in writer.fieldnames}
            row.update(
                scenario_id=scope,
                metric=name,
                units="USD_per_successful_task"
                if name == "cost_per_successful_task"
                else "proportion",
            )
            if name == "cost_per_successful_task":
                row["denominator"] = record["successful_live_tasks"]
            writer.writerow(row)
        for statistic in ("median", "p95"):
            latency = summary["latency"]
            writer.writerow(
                {
                    "scenario_id": scope,
                    "metric": f"{statistic}_latency_seconds",
                    "value": latency[f"{statistic}_seconds"],
                    "denominator": latency["count"],
                    "status": "available" if latency["count"] else "unavailable",
                    "reason": latency["label"],
                    "units": "seconds",
                }
            )
    if "security" in document["summary"]:
        security = document["summary"]["security"]
        coverage = security.get("attack_outcome_coverage", {})
        if "determinate_trials" in coverage:
            coverage_keys = ATTACK_COUNTS if candidate else tuple(coverage)
            counts = {
                "configured_trials": security["configured_trials"],
                "trial_metadata_unavailable": security["trial_metadata_unavailable"],
                **{
                    k: coverage[k]
                    for k in coverage_keys
                    if k in coverage
                    and k not in {"coverage", "attack_success", "units", "schema_version"}
                },
            }
            for name, value in counts.items():
                writer.writerow(
                    dict(
                        scenario_id="__security__",
                        metric=name,
                        value=value,
                        status="available" if value is not None else "unavailable",
                        units="trials",
                    )
                )
            for name in ("coverage", "attack_success"):
                metric = coverage[name]
                writer.writerow(
                    dict(
                        scenario_id="__security__",
                        metric="attack_outcome_" + name,
                        units="proportion",
                        **metric,
                    )
                )
        if "population" in security:
            population = security["population"]
            names = POPULATION_COUNTS if candidate else population
            for name in names:
                if name in POPULATION_COUNTS and name in population:
                    value = population[name]
                    writer.writerow(
                        dict(
                            scenario_id="__population__",
                            metric=name,
                            value=value,
                            status="available" if value is not None else "unavailable",
                            units="trials",
                        )
                    )
        objectives = security["per_objective"]
        if candidate:
            objectives = dict(sorted(objectives.items()))
        for name, metric in {
            **objectives,
            "defensive_false_positive_rate": security["defensive_false_positive_rate"],
            "benign_task_success": security["benign_task_success"],
        }.items():
            writer.writerow(
                {
                    "scenario_id": "__security__",
                    "metric": name,
                    "units": "proportion",
                    **{
                        key: metric.get(key)
                        for key in writer.fieldnames
                        if key not in {"scenario_id", "metric", "units"}
                    },
                }
            )
    for result in document["results"]:
        p = result.get("scoring_provenance", {})
        if "requested_evaluator_version" in p:
            for name in ("requested_evaluator_version", "effective_evaluator_version"):
                writer.writerow(
                    dict(
                        scenario_id="__trial__:" + result["trial_id"],
                        metric=name,
                        value=p[name],
                        status="available" if p[name] else "not_executed",
                        units="version",
                    )
                )
    contents = {
        "results.json": json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True),
        "metrics.csv": output.getvalue(),
        "report.md": markdown(document),
    }
    return {name: text.encode("utf-8") for name, text in contents.items()}
