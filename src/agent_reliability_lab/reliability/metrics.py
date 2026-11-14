"""Versioned operational metrics, separate from evaluator and renderer semantics."""

import csv
import io
import json
from pathlib import Path

from agent_reliability_lab.reliability.diagnostics import observed_trial_gaps

VERSION = "reliability-1.0.0"

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
    completed_chains = 0
    determinate = 0
    contradictions = 0
    for row in evidence:
        result = row.get("reconciliation")
        if isinstance(result, dict) and result.get("complete") is True:
            completed_chains += 1
        if row.get("eligible") is True and isinstance(row.get("objective_success"), bool):
            determinate += 1
        if isinstance(result, dict) and isinstance(result.get("errors"), list):
            contradictions += "contradictory_records" in observed_trial_gaps(row)
    population = len(evidence)
    groups = [
        ("outcome_ascertainment", determinate),
        ("unknown_outcome", population - determinate),
        ("chain_completeness", completed_chains),
    ]
    # Older evidence does not expose a uniform contradiction assessment for each row.
    inspectable = all(
        isinstance(row.get("reconciliation"), dict)
        and isinstance(row["reconciliation"].get("errors"), list)
        for row in evidence
    )
    return [metric(name, count, population, scope) for name, count in groups] + [
        metric("contradiction", contradictions, population, scope)
        if inspectable
        else metric("contradiction", None, None, scope)
    ]


def revised_metrics(provider, attempts, receipt_verified):
    terminal = provider["delivery"]
    determinate = terminal in {"provider_rejected", "delivered", "failed"}
    consistent = terminal != "contradictory"
    scope = "One scripted, synthetic notification intent"
    chain = receipt_verified and provider["acknowledged"] and determinate
    return [
        metric("outcome_ascertainment", int(determinate), 1, scope),
        metric("unknown_outcome", int(not determinate), 1, scope),
        metric("chain_completeness", int(chain), 1, scope),
        metric("contradiction", int(not consistent), 1, scope),
        metric("external_confirmation", int(determinate), 1, scope),
        metric(
            "duplicate_effect",
            0 if receipt_verified else None,
            1 if receipt_verified else None,
            scope,
        ),
        metric(
            "retry_deduplication",
            sum(a["receipt_reused"] is True for a in attempts),
            sum(a["receipt_reused"] is not None for a in attempts),
            scope,
        ),
        metric("conflicting_intent_rejection", 0, 0, scope),
        metric("verified_recovery", int(receipt_verified), 1, scope),
        metric("unknown_commitment", int(not receipt_verified), 1, scope),
        metric("receipt_reconciliation", int(receipt_verified), 1, scope),
    ]


def render(document, format_name):
    if format_name == "json":
        return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    columns = ["name", "numerator", "denominator", "value", "reason", "scope", "version"]
    if format_name == "csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream, fieldnames=["report_id", "delivery", *columns], extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(
            {
                "report_id": document["report_id"],
                "delivery": document["provider"]["delivery"],
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
    lines.extend(
        "| "
        + " | ".join("Unavailable" if row[key] is None else str(row[key]) for key in columns)
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
