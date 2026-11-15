"""Versioned operational metrics, separate from evaluator and renderer semantics."""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from agent_reliability_lab.reliability.diagnostics import observed_trial_gaps

VERSION = "reliability-1.3.0"
PREVIOUS_VERSION = "reliability-1.1.0"
UNSIGNED_VERSIONS = frozenset({"reliability-1.0.0", PREVIOUS_VERSION, "reliability-1.2.0"})

DEFINITIONS = {
    "outcome_ascertainment": "Determinate outcomes / applicable observations",
    "unknown_outcome": "Unresolved outcomes / applicable observations",
    "chain_completeness": "Complete required chains / applicable chains",
    "contradiction": "Material contradictions / inspected observations",
    "external_confirmation": "Confirmed delivery or negative provider outcome / local intents",
    "duplicate_effect": "Operations with multiple mutations / operations with known mutation count",
    "retry_deduplication": "Matching retries reusing one receipt / resolved matching retries",
    "conflicting_intent_rejection": "Rejected conflicts / resolved conflicting requests",
    "verified_recovery": "Verified recovery / eligible faults with known recovery outcome",
    "unknown_commitment": "Unresolved commitment / dispatched logical writes",
    "receipt_reconciliation": "Reconciled receipts / writes requiring receipt verification",
}

QUALITY_NAMES = ("outcome_ascertainment", "unknown_outcome", "chain_completeness", "contradiction")


def metric(name, numerator, denominator, scope):
    if denominator is not None and (numerator is None or not 0 <= numerator <= denominator):
        raise ValueError("invalid operational metric population")
    if denominator is None and numerator is not None:
        raise ValueError("unavailable population cannot have a measured numerator")
    return dict(
        name=name,
        numerator=numerator,
        denominator=denominator,
        scope=scope,
        version=VERSION,
        value=numerator / denominator if denominator else None,
        reason=None
        if denominator
        else ("population_unavailable" if denominator is None else "no_applicable_observations"),
        definition=DEFINITIONS[name],
    )


def evidence_quality(document):
    """Summarize pinned score rows without regenerating their scores."""
    evidence = document.get("results")
    scope = "Pinned trial score revisions · " + str(
        document.get("evaluator_version")
        or (document.get("report_manifest") or {}).get("metric_definition_version")
        or "unknown"
    )
    if not isinstance(evidence, list) or any(not isinstance(row, dict) for row in evidence):
        return [metric(name, None, None, scope) for name in QUALITY_NAMES]
    inspected_chains = 0
    completed_chains = 0
    determinate = 0
    contradictions = 0
    for row in evidence:
        result = row.get("reconciliation")
        if isinstance(result, dict) and isinstance(result.get("complete"), bool):
            inspected_chains += 1
            completed_chains += result["complete"]
        if row.get("eligible") is True and isinstance(row.get("objective_success"), bool):
            determinate += 1
        if isinstance(result, dict) and isinstance(result.get("errors"), list):
            contradictions += "contradictory_records" in observed_trial_gaps(row)
    population = len(evidence)
    groups = [
        ("outcome_ascertainment", determinate),
        ("unknown_outcome", population - determinate),
    ]
    # Older evidence does not expose a uniform contradiction assessment for each row.
    inspectable = all(
        isinstance(row.get("reconciliation"), dict)
        and isinstance(row["reconciliation"].get("errors"), list)
        for row in evidence
    )
    chain = (
        metric("chain_completeness", completed_chains, inspected_chains, scope)
        if (inspected_chains or not population)
        else metric("chain_completeness", None, None, scope)
    )
    return [metric(name, count, population, scope) for name, count in groups] + [
        chain,
        metric("contradiction", contradictions, population, scope)
        if inspectable
        else metric("contradiction", None, None, scope),
    ]


@dataclass(frozen=True)
class Observation:
    """One distinct eligible observation. None means its outcome remains unresolved."""

    identity: str
    outcome: bool | None


def revised_metrics(populations: dict[str, list[Observation] | None], *, scope: str):
    records = []
    for name in DEFINITIONS:
        population = populations.get(name)
        if population is None:
            records.append(metric(name, None, None, scope))
            continue
        if len({row.identity for row in population}) != len(population):
            raise ValueError("duplicate operational observation")
        known = [row for row in population if row.outcome is not None]
        if not known and population:
            record = metric(name, None, None, scope)
            record["reason"] = "outcomes_unresolved"
        else:
            record = metric(name, sum(row.outcome is True for row in known), len(known), scope)
        record["unresolved"] = len(population) - len(known)
        records.append(record)
    return records


def notification_metrics(
    provider,
    *,
    operation_id,
    mutation_count,
    receipt_reconciled,
    attempt_observations,
    faults,
    conflicts,
    dispatched,
):
    identity = provider["notification_id"]
    terminal = provider["delivery"]
    terminal_observed = terminal in {"provider_rejected", "delivered", "failed"}
    retry_success = bool(attempt_observations) and any(
        attempt.outcome is True for attempt in attempt_observations
    )
    contradictory = (
        terminal == "contradictory"
        or (
            mutation_count == 0
            and (terminal_observed or receipt_reconciled is True or retry_success)
        )
        or (
            retry_success
            and (
                receipt_reconciled is False or (mutation_count is not None and mutation_count != 1)
            )
        )
    )
    if attempt_observations and (mutation_count != 1 or receipt_reconciled is not True):
        attempt_observations = [
            Observation(attempt.identity, None) if attempt.outcome is True else attempt
            for attempt in attempt_observations
        ]
    determinate = terminal_observed and not contradictory and mutation_count is not None

    inspected = provider.get("local_intent") == "recorded" or contradictory
    complete = (
        None
        if not inspected
        else bool(
            not contradictory
            and mutation_count == 1
            and receipt_reconciled
            and provider["acknowledged"]
            and determinate
        )
    )

    def row(value):
        return [Observation(identity, value)]

    return revised_metrics(
        {
            "outcome_ascertainment": row(determinate),
            "unknown_outcome": row(not determinate),
            "chain_completeness": row(complete),
            "contradiction": row(contradictory if inspected else None),
            "external_confirmation": row(determinate),
            "duplicate_effect": [
                Observation(operation_id, None if mutation_count is None else mutation_count > 1)
            ],
            "retry_deduplication": attempt_observations,
            "conflicting_intent_rejection": conflicts,
            "verified_recovery": (
                None
                if faults is None
                else [
                    Observation(fault.identity, None)
                    if contradictory
                    or (
                        fault.outcome is True
                        and (mutation_count != 1 or receipt_reconciled is not True)
                    )
                    else fault
                    for fault in faults
                ]
            ),
            "unknown_commitment": [Observation(operation_id, mutation_count is None)]
            if dispatched
            else [],
            "receipt_reconciliation": [
                Observation(
                    operation_id, None if mutation_count in (None, 0) else receipt_reconciled
                )
            ],
        },
        scope="One scripted, synthetic notification intent",
    )


def render(document, format_name):
    if format_name == "json":
        return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    columns = ["name", "numerator", "denominator", "value", "reason", "scope", "version"]
    current = document.get("version") in {VERSION, *UNSIGNED_VERSIONS - {"reliability-1.0.0"}}
    if current:
        columns += ["unresolved"]
    if format_name == "csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "report_id",
                "delivery",
                *(["revision", "previous_report_id"] if current else []),
                *columns,
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(
            {
                "report_id": document["report_id"],
                "delivery": document["provider"]["delivery"],
                "revision": document["revision"],
                "previous_report_id": document.get("previous_report_id"),
                **row,
            }
            for row in document["metrics"]
        )
        return stream.getvalue()
    if format_name != "md":
        raise ValueError("unknown reliability export format")
    lines = [
        "# Synthetic notification reliability",
        "",
        "Operational evidence from a scripted demonstration.",
        "",
        f"- Revision {document['revision']}",
        f"- Report `{document['report_id']}`",
        f"- Execution `{document['execution_id']}`",
        f"- Delivery outcome **{document['provider']['delivery']}**",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    if current:
        lines.insert(7, f"- Predecessor `{document.get('previous_report_id') or 'None'}`")
    lines.extend(
        "| "
        + " | ".join("Unavailable" if row.get(key) is None else str(row[key]) for key in columns)
        + " |"
        for row in document["metrics"]
    )
    return "\n".join(lines) + "\n"


def export(document, root):
    folder = Path(root) / document["report_id"]
    folder.mkdir(parents=True, exist_ok=False)
    for format_name in ("json", "csv", "md"):
        (folder / f"reliability.{format_name}").write_bytes(render(document, format_name).encode())
    return folder
