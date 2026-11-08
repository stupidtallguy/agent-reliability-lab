"""Versioned JSON/CSV/Markdown reports; never overwrite prior exports."""

import csv
import io
import json
from pathlib import Path

from agent_reliability_lab.adversarial.reporting import experimental_summary
from agent_reliability_lab.evaluation.metrics import summarize
from agent_reliability_lab.evaluation.persistence import EvaluationStore

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


def report(store: EvaluationStore, experiment_id: str) -> dict:
    manifest = store.experiment(experiment_id)["manifest"]
    trials = store.list_trials(experiment_id=experiment_id)
    scores = []
    for trial in trials:
        revisions = store.scores(trial["trial_id"])
        if not revisions:
            raise ValueError(
                "experiment has unscored trials; inspect its lifecycle before reporting"
            )
        scores.append(revisions[-1])
    summary = summarize(scores)
    if any(score.experimental for score in scores):
        summary["security"] = experimental_summary(scores)
    summary["metric_definitions"] = DEFINITIONS
    summary["per_scenario"] = {
        scenario_id: summarize([score for score in scores if score.scenario_id == scenario_id])
        for scenario_id in sorted({score.scenario_id for score in scores})
    }
    summary["per_category"] = {
        category: summarize([score for score in scores if score.category == category])
        for category in sorted({score.category for score in scores})
    }
    report_id = store.save_report(experiment_id, scores, summary)
    return {
        "schema_version": "1.0",
        "report_id": report_id,
        "experiment_id": experiment_id,
        "manifest": manifest,
        "summary": summary,
        "results": [score.model_dump(mode="json") for score in scores],
        "cleanup": {trial["trial_id"]: trial["cleanup"] for trial in trials},
    }


def markdown(document: dict) -> str:
    summary, manifest = document["summary"], document["manifest"]
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
            json.dumps(summary["security"], indent=2),
            "```",
            "",
        ]
    for name, metric in summary["metrics"].items():
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
    destination = root / document["experiment_id"] / document["report_id"]
    destination.mkdir(parents=True, exist_ok=False)
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
    groups = {"__all__": document["summary"], **document["summary"]["per_scenario"]}
    for scope, summary in groups.items():
        for name, record in summary["metrics"].items():
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
        for name, metric in {
            **security["per_objective"],
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
    contents = {
        "results.json": json.dumps(document, indent=2, ensure_ascii=False),
        "metrics.csv": output.getvalue(),
        "report.md": markdown(document),
    }
    for filename, content in contents.items():
        with (destination / filename).open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
    return destination
