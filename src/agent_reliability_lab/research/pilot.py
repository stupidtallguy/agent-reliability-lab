"""Reuse CP12 scheduling, capture, scoring and pair verification for the CP15 pilot."""

import csv
import io
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from agent_reliability_lab.agent.provenance import verify_projection
from agent_reliability_lab.evaluation.contracts import Evidence, ModelPrice, PriceBook
from agent_reliability_lab.evaluation.runner import trial_agent_config
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import (
    _config,
    execute_benchmark,
    schedule,
    verify_result,
)
from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker
from agent_reliability_lab.research.pilot_contracts import (
    PilotArm,
    PilotLimits,
    PilotModel,
    PilotPlan,
    PilotReport,
)
from agent_reliability_lab.research.pilot_model import OfflinePilotModel, reply_fingerprint

METHODOLOGY = (
    "Exploratory development-only OpsDesk fixtures. Both arms use the same frozen scripts, "
    "seeds, initial fixtures and execution limits in independent sandboxes. The guarded arm "
    "changes task scope and observation framing, so the contrast does not isolate mechanisms. "
    "The independent evaluator verifies task and security outcomes from pinned trial evidence. "
    "The template-clustered intervals are exploratory and small populations limit inference. "
    "Provider replies, tokens and USD are simulated. Missing usage retains the full capacity hold."
)


def validate_plan(store, plan):
    if plan.kind != "benchmark_pilot_plan":
        raise ValueError("a frozen development pilot plan is required")
    protocol = store.get(plan.protocol)
    if protocol.kind != "benchmark_protocol":
        raise ValueError("pilot requires a development benchmark protocol")
    dataset = store.get(protocol.dataset)
    slots, catalog = schedule(dataset, protocol)
    if plan.schedule_hash != digest(slots):
        raise ValueError("pilot schedule differs from the frozen development protocol")
    if plan.supersedes:
        previous = store.get(plan.supersedes)
        if previous.ledger_id == plan.ledger_id:
            raise ValueError("an amended pilot requires a new budget ledger")
    if plan.mode == "groq_qualification":
        if protocol.mode != "provider_development_exploratory" or any(
            slot["partition"] != "development" for slot in slots
        ):
            raise ValueError("Groq qualification requires an existing development scenario")
        return [
            PilotArm(
                slot="groq_qualification",
                arm="baseline",
                scenario="groq_qualification",
                tenant="groq_qualification",
                actor="groq_qualification",
                script_config_hash=digest(protocol.model.model_dump(mode="json")),
                maximum_output_tokens=plan.limits.maximum_output_tokens,
            )
        ]
    arms = []
    for slot in slots:
        spec = catalog[slot["scenario_id"]]
        scenario = spec.case.scenario
        if scenario.metadata.split != "development":
            raise ValueError("pilot requires development scope on the executable scenario")
        for arm in slot["order"]:
            host = trial_agent_config(
                scenario,
                _config(protocol, spec, arm, "0" * 32),
                "pilot_plan",
                protocol.source_commit,
                protocol.scripts.get(spec.scenario_id),
            )
            arms.append(
                PilotArm(
                    slot=slot["slot"],
                    arm=arm,
                    scenario=spec.scenario_id,
                    tenant=scenario.actor.tenant_id,
                    actor=scenario.actor.actor_id,
                    script_config_hash=digest(host.model.model_dump(mode="json")),
                    maximum_output_tokens=host.budgets.max_output_tokens,
                )
            )
    if any(a.maximum_output_tokens > plan.limits.maximum_output_tokens for a in arms):
        raise ValueError("pilot output limit is below the frozen host request limit")
    return arms


def draft_pilot(store, protocol_ref, identity, fault="none"):
    protocol = store.get(protocol_ref)
    if protocol.kind != "benchmark_protocol":
        raise ValueError("pilot requires a development benchmark protocol")
    slots, _ = schedule(store.get(protocol.dataset), protocol)
    model = PilotModel(model_id="cp15-fixture-v1", allowed_models=("cp15-fixture-v1",))
    price = PriceBook(
        version="cp15-fixture-v1",
        prices=[
            ModelPrice(
                provider=model.provider,
                model_id=model.model_id,
                effective_from=datetime(2020, 1, 1, tzinfo=UTC),
                provenance="synthetic_fixture_rate",
                input_rate=Decimal("1.25"),
                output_rate=Decimal("2.50"),
            )
        ],
    )
    calls = min(10000, len(slots) * 2 * protocol.budgets.max_llm_calls)
    input_ceiling = protocol.budgets.max_context_bytes * 2
    output_ceiling = protocol.budgets.max_output_tokens
    fixture_price = price.prices[0]
    usd_ceiling = (
        calls
        * (input_ceiling * fixture_price.input_rate + output_ceiling * fixture_price.output_rate)
        / Decimal(1000000)
    )
    plan = PilotPlan(
        identity=identity,
        author=protocol.author,
        created_at=datetime.now(UTC),
        mode="offline_fixture",
        protocol=protocol_ref,
        schedule_hash=digest(slots),
        ledger_id=uuid.uuid4().hex,
        model=model,
        pricing=price,
        pricing_hash=digest(price.model_dump(mode="json")),
        fixture_fault=fault,
        limits=PilotLimits(
            total_calls=calls,
            calls_per_scenario=protocol.repetitions * 2 * protocol.budgets.max_llm_calls,
            retries_per_turn=0,
            maximum_input_tokens=input_ceiling,
            maximum_output_tokens=output_ceiling,
            total_tokens=calls * (input_ceiling + output_ceiling),
            maximum_usd=usd_ceiling,
            duration_seconds=1800,
        ),
    )
    validate_plan(store, plan)
    return plan


def open_pilot(store, plan_ref, protocol_ref):
    plan = store.get(plan_ref)
    arms = validate_plan(store, plan)
    if plan.mode != "offline_fixture" or plan.protocol != protocol_ref:
        raise ValueError("live pilot execution is disabled or the plan does not match the run")
    broker = PilotBudgetBroker(store.engine, store.scope, plan)
    broker.initialize()
    broker.open(plan, arms)
    by_arm = {(arm.slot, arm.arm): arm for arm in arms}

    def make_model(run_ref, slot, arm, script_config):
        return OfflinePilotModel(broker, plan, by_arm[(slot, arm)], run_ref, script_config)

    return make_model


def _verify_request(evidence, calls):
    verify_projection(Evidence.model_validate_json(json.dumps(evidence)))
    starts = {
        r["reference"]: r["body"] for r in evidence["provenance"] if r["kind"] == "model_started"
    }
    completions = {
        r["reference"]: r["body"]["reply"]
        for r in evidence["provenance"]
        if r["kind"] == "model_completed"
    }
    if not set(calls) <= set(starts):
        raise ValueError("pilot ledger contains an unsealed model attempt")
    for request_id, sealed in starts.items():
        row = calls.get(request_id)
        reply = completions.get(request_id)
        if row is None:
            if reply is not None:
                raise ValueError("completed model response has no durable pilot reservation")
            continue
        submitted = row["request"]
        if any(submitted[k] != sealed[k] for k in ("input_hash", "execution_id", "turn")):
            raise ValueError("pilot reservation differs from sealed request")
        if reply is not None:
            observation = row["observation"]
            expected = {
                "response_hash": reply_fingerprint(reply),
                "provider_request_id": reply["provider_request_id"],
                "reported_model": reply["reported_model"],
                "outcome": "completed",
            }
            for key in ("input_tokens", "output_tokens"):
                if reply["usage"][key] is not None:
                    expected[key] = reply["usage"][key]
            if observation is None or any(observation[k] != v for k, v in expected.items()):
                raise ValueError("pilot usage differs from sealed response")
    return len(starts) - len(calls)


def _join_budget(store, result, plan, rows):
    arms = {(arm.slot, arm.arm): arm.model_dump(mode="json") for arm in validate_plan(store, plan)}
    inventory, requests_without_reservation = [], 0
    for pair in result["pairs"]:
        for name, arm in pair["arms"].items():
            key = (pair["slot"], name)
            calls = {
                attempt: data
                for attempt, data in rows.items()
                if data["request"]["execution_id"] == arm["execution_id"]
            }
            if any(data["request"]["allocation"] != arms[key] for data in calls.values()):
                raise ValueError("pilot model attempt crosses frozen arm or tenant scope")
            trial = store.evaluations.trial(arm["trial_id"])
            evidence = trial["evidence"]
            if evidence is not None:
                requests_without_reservation += _verify_request(evidence, calls)
            inventory.append(
                dict(
                    slot=pair["slot"],
                    arm=name,
                    execution_id=arm["execution_id"],
                    score_pinned_evidence_available=evidence is not None,
                    attempt_ids=list(calls),
                )
            )
    linked = [ref for arm in inventory for ref in arm["attempt_ids"]]
    if set(linked) != set(rows) or len(linked) != len(rows):
        raise ValueError("pilot budget attempt has no unique benchmark execution")
    return inventory, requests_without_reservation


def _usage(rows):
    active = [item for item in rows.values() if item["state"] != "cancelled"]
    sent = [item for item in active if item["state"] != "reserved"]
    settled = [item for item in sent if item["state"] == "settled"]
    pending = [item for item in active if item["state"] != "settled"]
    observations = [item["observation"] for item in sent if item["observation"] is not None]

    def measurements(key):
        counts = [item[key] for item in observations if item[key] is not None]
        return {
            "observed": len(counts),
            "dispatched": len(sent),
            "sum_observed": sum(counts) if counts else None,
        }

    return dict(
        active_reservations=len(active),
        physical_dispatches=len(sent),
        settlements=len(settled),
        unobserved_dispatch_outcomes=sum(i["observation"] is None for i in sent),
        dispatched_unsettled=len(sent) - len(settled),
        pending_capacity_usd=str(sum((Decimal(i["charged_usd"]) for i in pending), Decimal(0))),
        settled_conservative_usd=str(sum((Decimal(i["charged_usd"]) for i in settled), Decimal(0)))
        if settled
        else None,
        reported_input_tokens=measurements("input_tokens"),
        reported_output_tokens=measurements("output_tokens"),
        provider_latency_ms=measurements("elapsed_ms"),
        provider_billed_observations=sum(i["billed_usd"] is not None for i in observations),
    )


def _document(store, plan_ref, result_ref, event_count=None):
    plan, artifact = store.get(plan_ref), store.get(result_ref)
    if plan.kind != "benchmark_pilot_plan" or artifact.kind != "benchmark_result":
        raise ValueError("pilot report references have incorrect kinds")
    run = store.get(artifact.run)
    if run.pilot != plan_ref or run.protocol != plan.protocol:
        raise ValueError("pilot report and benchmark run pin different evidence")
    result = verify_result(store, artifact)
    broker = PilotBudgetBroker(store.engine, store.scope, plan)
    events = broker.snapshot(event_count)
    rows = {event["attempt_id"]: event["body"] for event in events}
    inventory, requests_without_reservation = _join_budget(store, result, plan, rows)
    document = dict(
        schema_version="development-pilot-report-1.0.0",
        interpretation="offline_fixture_exploratory",
        methodology=METHODOLOGY,
        plan=plan_ref.model_dump(mode="json"),
        benchmark_result=result_ref.model_dump(mode="json"),
        model=plan.model.model_dump(mode="json"),
        model_hash=digest(plan.model.model_dump(mode="json")),
        pricing=plan.pricing.model_dump(mode="json"),
        pricing_hash=plan.pricing_hash,
        ledger_id=plan.ledger_id,
        schedule_hash=plan.schedule_hash,
        limits=plan.limits.model_dump(mode="json"),
        fixture_fault=plan.fixture_fault,
        event_count=len(events),
        event_hash=digest(events),
        provider_events=events,
        arm_inventory=inventory,
        model_requests_without_reservation=requests_without_reservation,
        usage=_usage(rows),
        benchmark=result,
    )
    if run.live_authorization is not None:
        authority = store.get(run.live_authorization)
        if any(
            row["request"].get("authorization_hash") != run.live_authorization.content_hash
            or not row["request"].get("wire_hash")
            for row in rows.values()
        ):
            raise ValueError("provider events differ from the frozen execution authorization")
        document.update(
            schema_version="development-http-pilot-report-1.0.0",
            interpretation=authority.mode,
            authorization=run.live_authorization.model_dump(mode="json"),
            provider_profile=authority.profile.model_dump(mode="json"),
            methodology=(
                "Exploratory feasibility over two counterbalanced pairs of one template. "
                "The guarded arm changes task scope and observation framing. Both arms share the "
                "provider configuration and independent synthetic sandboxes. Scores are verified "
                "against captured tool evidence. Costs are estimates at frozen prices. Missing "
                "usage keeps the reservation. "
                + (
                    "This run used simulated HTTP responses."
                    if authority.mode == "mock_http"
                    else "Provider usage remains separate from independently verified invoices."
                )
            ),
        )
        if plan.model.provider == "groq":
            if any(
                (observation := row["observation"]) is not None
                and observation["outcome"] == "completed"
                and (
                    observation.get("system_fingerprint")
                    != authority.profile.expected_system_fingerprint
                    or observation["reported_model"] != authority.profile.returned_model
                    or observation.get("route_mismatch") is True
                    or observation["provider_request_id"] is None
                )
                for row in rows.values()
            ):
                raise ValueError("Groq provider observation differs from the frozen route")
            document.update(
                schema_version="development-groq-pilot-report-1.0.0",
                provider_profile=authority.profile.model_dump(
                    mode="json", exclude={"free_key_commitment"}
                ),
                financial_verification={
                    "local_pricing_basis": (
                        "simulated_free_plan"
                        if authority.mode == "mock_http"
                        else "operator_attested_free_plan"
                    ),
                    "provider_charge_status": "unavailable",
                    "invoice_status": "unverified",
                },
            )
    return document


async def run_pilot(store, plan_ref):
    plan = store.get(plan_ref)
    if plan.kind != "benchmark_pilot_plan" or plan.mode != "offline_fixture":
        raise ValueError("live pilot execution is disabled")
    result_ref, _ = await execute_benchmark(store, plan.protocol, pilot_ref=plan_ref)
    return publish_pilot(store, plan_ref, result_ref)


def publish_pilot(store, plan_ref, result_ref):
    plan = store.get(plan_ref)
    document = _document(store, plan_ref, result_ref)
    report = PilotReport(
        identity=result_ref.identity,
        author=plan.author,
        created_at=datetime.now(UTC),
        plan=plan_ref,
        benchmark_result=result_ref,
        event_count=document["event_count"],
        event_hash=document["event_hash"],
        report_hash=digest(document),
    )
    return store.append(report)


def verify_pilot_report(store, report):
    if (
        report.kind != "benchmark_pilot_report"
        or report.identity != report.benchmark_result.identity
    ):
        raise ValueError("pilot report requires the exact frozen run identity")
    document = _document(store, report.plan, report.benchmark_result, report.event_count)
    if document["event_hash"] != report.event_hash or digest(document) != report.report_hash:
        raise ValueError(
            "pilot report does not reproduce from pinned budget and evaluation evidence"
        )
    return document


def render_pilot(document):
    """Deterministic exports of the same report, with CSV rows and readable Markdown."""
    raw = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    benchmark = document["benchmark"]
    metadata = {
        key: document[key]
        for key in (
            "plan",
            "benchmark_result",
            "model_hash",
            "pricing_hash",
            "event_hash",
            "event_count",
            "ledger_id",
        )
    } | {key: benchmark[key] for key in ("source_commit", "evaluator_version", "planned_pairs")}
    if "authorization" in document:
        metadata.update(
            authorization=document["authorization"], interpretation=document["interpretation"]
        )
    if "financial_verification" in document:
        metadata["financial_verification"] = document["financial_verification"]
    result_rows = [("metadata", "", key, value) for key, value in metadata.items()] + [
        ("usage", "", key, value) for key, value in document["usage"].items()
    ]
    result_rows.append(("method", "", "methodology", document["methodology"]))
    result_rows.append(("statistics", "", "paired_summary", benchmark["summary"]))
    for pair in benchmark["pairs"]:
        result_rows.append(
            (
                "pair",
                pair["slot"],
                "comparison",
                {"status": pair["comparison"], "reason": pair["exclusion"], "order": pair["order"]},
            )
        )
        for arm, values in pair["arms"].items():
            result_rows.append(("measurement", pair["slot"], arm, values))
    for event in document["provider_events"]:
        result_rows.append(("provider_event", event["attempt_id"], str(event["sequence"]), event))
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("category", "reference", "field", "value_json"))
    markdown = [
        "# Development pilot",
        "",
        document["methodology"],
        "",
        "| Category | Reference | Field | Value |",
        "| --- | --- | --- | --- |",
    ]
    for category, reference, key, value in result_rows:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False)
        writer.writerow((category, reference, key, encoded))
        cell = (
            encoded.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("|", "&#124;")
            .replace("`", "&#96;")
        )
        markdown.append(f"| {category} | {reference} | {key} | {cell} |")
    return {"json": raw, "csv": buffer.getvalue(), "md": "\n".join(markdown) + "\n"}
