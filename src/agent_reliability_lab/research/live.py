"""Development-only activation, authorization, and read-only readiness checks."""

import os
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from agent_reliability_lab.agent.config import ModelConfig
from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.runner import provenance
from agent_reliability_lab.opsdesk.database import lock
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import _source_matches, schedule
from agent_reliability_lab.research.contracts import parse_artifact
from agent_reliability_lab.research.live_contracts import GroqProfile
from agent_reliability_lab.research.persistence import artifacts
from agent_reliability_lab.research.pilot import validate_plan
from agent_reliability_lab.research.pilot_contracts import (
    GROQ_PILOT_CALLS,
    PilotLimits,
    PilotModel,
    PilotPlan,
)

# Deployment/build fuse. CP16 does not ship a CLI or environment override for this.
PUBLIC_PROVIDER_NETWORK_ENABLED = False
GROQ_FREE_NETWORK_ENABLED = False
PROVIDER_PROTOCOL = "provider_development_exploratory"
TEST_DATABASES = {"opsdesk_lab_ci", "opsdesk_lab_test"}


class ActivationBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require_disposable(store):
    if (
        store.engine.url.database not in TEST_DATABASES
        or os.environ.get("OPSDESK_TEST_OWNED") != "1"
    ):
        raise ActivationBlocked("disposable_database_required")


def validate_authorization(store, authorization, plan=None):
    if authorization.kind != "benchmark_live_authorization":
        raise ActivationBlocked("wrong_authorization_kind")
    if plan is None:
        plan = store.get(authorization.pilot)
    protocol = store.get(plan.protocol) if plan.kind == "benchmark_pilot_plan" else None
    profile = authorization.profile
    if (
        protocol is None
        or store.reference(plan) != authorization.pilot
        or authorization.scope != store.scope
        or authorization.identity != "auth_" + plan.ledger_id
        or plan.mode != "future_live_requested"
        or protocol.kind != "benchmark_protocol"
        or protocol.mode != PROVIDER_PROTOCOL
        or authorization.protocol != plan.protocol
        or authorization.experiment != plan.identity
        or authorization.schedule_hash != plan.schedule_hash
        or authorization.pricing_hash != plan.pricing_hash
        or authorization.ledger_id != plan.ledger_id
        or authorization.configuration_hash != digest(plan.model.model_dump(mode="json"))
        or authorization.limits != plan.limits
        or (profile.provider, profile.requested_model, profile.returned_model)
        != (
            plan.model.provider,
            plan.model.model_id,
            plan.model.model_id,
        )
        or (protocol.model.provider, protocol.model.model_id)
        != (plan.model.provider, plan.model.model_id)
        or plan.model.allowed_models != (plan.model.model_id,)
    ):
        raise ActivationBlocked("authorization_binding_mismatch")
    if (plan.limits.maximum_input_tokens, plan.limits.maximum_output_tokens) != (
        profile.input_ceiling,
        profile.output_ceiling,
    ):
        raise ActivationBlocked("token_ceiling_mismatch")
    validate_plan(store, plan)
    if authorization.supersedes:
        previous = store.get(authorization.supersedes)
        if previous.pilot != authorization.pilot or previous.scope != authorization.scope:
            raise ActivationBlocked("authorization_lineage_mismatch")
    return protocol


def active_authorization(connection, scope, reference, plan_hash):
    """Use the artifact publisher's lock so a committed revocation wins before dispatch."""
    if reference is None or reference.kind != "benchmark_live_authorization":
        raise ActivationBlocked("operator_authorization_required")
    lock(connection, "research:" + scope, shared=True)
    rows = (
        connection.execute(
            sa.select(artifacts.c.body, artifacts.c.content_hash)
            .where(
                artifacts.c.scope == scope,
                artifacts.c.kind == reference.kind,
                artifacts.c.identity == reference.identity,
            )
            .order_by(artifacts.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if (
        rows is None
        or rows["content_hash"] != reference.content_hash
        or digest(rows["body"]) != reference.content_hash
    ):
        raise ActivationBlocked("authorization_missing_or_superseded")
    authority = parse_artifact(rows["body"])
    if (
        authority.scope != scope
        or authority.version != reference.version
        or authority.identity != reference.identity
        or authority.pilot.content_hash != plan_hash
        or authority.decision != "authorized"
    ):
        raise ActivationBlocked("authorization_binding_mismatch_or_revoked")
    now = connection.scalar(sa.select(sa.func.clock_timestamp()))
    if not authority.starts_at <= now < authority.deadline or authority.created_at > now:
        raise ActivationBlocked("authorization_outside_execution_window")
    issues = authority.profile.incompatibilities(authority.mode)
    if issues:
        raise ActivationBlocked(issues[0])
    if authority.mode == "paid_openai" and not PUBLIC_PROVIDER_NETWORK_ENABLED:
        raise ActivationBlocked("external_activation_locked")
    if authority.mode == "groq_free" and not GROQ_FREE_NETWORK_ENABLED:
        raise ActivationBlocked("groq_external_activation_locked")
    return authority


def draft_live(store, parent_ref, identity, profile, pricing, maximum_usd, scenario):
    require_disposable(store)
    parent = store.get(parent_ref)
    if (
        parent.kind != "benchmark_protocol"
        or parent.mode != "synthetic_exploratory"
        or scenario not in parent.scenarios
    ):
        raise ActivationBlocked("existing_development_protocol_required")
    dataset = store.get(parent.dataset)
    source = provenance(ExperimentConfig(experimental_evaluator=parent.evaluator_version))
    protocol = type(parent).model_validate_json(
        parent.model_copy(
            update=dict(
                identity=identity,
                version=1,
                supersedes=None,
                created_at=datetime.now(UTC),
                mode=PROVIDER_PROTOCOL,
                scenarios=[scenario],
                scripts={},
                repetitions=2,
                planned_pairs=2,
                model=ModelConfig(provider=profile.provider, model_id=profile.requested_model),
                budgets=parent.budgets.model_copy(
                    update={"max_output_tokens": profile.output_ceiling}
                ),
                allocation_rationale="Two opposite arm orders on one development template.",
                hypothesis=(
                    "The paired workflow can capture independently scored outcomes "
                    "and reconcile model usage."
                ),
                **{key: source[key] for key in ("source_commit", "source_hash", "lock_hash")},
            )
        ).model_dump_json()
    )
    if isinstance(profile, GroqProfile):
        protocol = protocol.model_copy(
            update={
                "budgets": protocol.budgets.model_copy(
                    update={"max_llm_calls": GROQ_PILOT_CALLS // 4}
                )
            }
        )
    slots, _ = schedule(dataset, protocol)
    model = PilotModel(
        provider=profile.provider,
        model_id=profile.requested_model,
        allowed_models=(profile.requested_model,),
    )
    calls = 4 * protocol.budgets.max_llm_calls
    plan = PilotPlan(
        identity=identity,
        author=protocol.author,
        created_at=protocol.created_at,
        mode="future_live_requested",
        protocol=store.reference(protocol),
        schedule_hash=digest(slots),
        ledger_id=uuid.uuid4().hex,
        model=model,
        pricing=pricing,
        pricing_hash=digest(pricing.model_dump(mode="json")),
        limits=PilotLimits(
            total_calls=calls,
            calls_per_scenario=calls,
            retries_per_turn=0,
            maximum_input_tokens=profile.input_ceiling,
            maximum_output_tokens=profile.output_ceiling,
            total_tokens=calls * (profile.input_ceiling + profile.output_ceiling),
            maximum_usd=maximum_usd,
            duration_seconds=900,
        ),
    )
    return protocol, plan


def draft_authorization(store, plan_ref, profile, mode, deadline):
    from agent_reliability_lab.research.live_contracts import LiveAuthorization

    require_disposable(store)
    plan = store.get(plan_ref)
    if plan.kind != "benchmark_pilot_plan":
        raise ActivationBlocked("provider_pilot_plan_required")
    now = datetime.now(UTC)
    artifact = LiveAuthorization(
        authorization_version=(
            "development-groq-free-1.0.0"
            if isinstance(profile, GroqProfile)
            else "development-http-1.0.0"
        ),
        identity="auth_" + plan.ledger_id,
        created_at=now,
        starts_at=now,
        deadline=deadline,
        author=plan.author,
        decision="authorized",
        mode=mode,
        scope=store.scope,
        protocol=plan.protocol,
        pilot=plan_ref,
        experiment=plan.identity,
        schedule_hash=plan.schedule_hash,
        configuration_hash=digest(plan.model.model_dump(mode="json")),
        pricing_hash=plan.pricing_hash,
        ledger_id=plan.ledger_id,
        profile=profile,
        limits=plan.limits,
    )
    validate_authorization(store, artifact, plan)
    return artifact


def preflight(store, plan_ref, authorization_ref=None):
    checks = {
        "credential_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "public_network_enabled": PUBLIC_PROVIDER_NETWORK_ENABLED,
    }
    issues = []
    try:
        require_disposable(store)
        checks["disposable_database"] = True
        plan = store.get(plan_ref)
        if plan.kind != "benchmark_pilot_plan" or plan.mode != "future_live_requested":
            raise ActivationBlocked("provider_pilot_plan_required")
        protocol = store.get(plan.protocol)
        if protocol.kind != "benchmark_protocol" or protocol.mode != PROVIDER_PROTOCOL:
            raise ActivationBlocked("provider_development_protocol_required")
        if (protocol.model.provider, protocol.model.model_id) != (
            plan.model.provider,
            plan.model.model_id,
        ):
            raise ActivationBlocked("provider_protocol_model_mismatch")
        arms = validate_plan(store, plan)
        if plan.model.provider == "groq":
            checks.update(
                credential_configured=bool(os.environ.get("GROQ_API_KEY", "").strip()),
                public_network_enabled=GROQ_FREE_NETWORK_ENABLED,
                rolling_day_call_limit=GROQ_PILOT_CALLS,
                provider_invoice_verified=False,
            )
        checks["development_only"] = True
        checks["held_out_enabled"] = False
        checks["sdk_retries"] = plan.model.sdk_retries
        checks["source_matches"] = _source_matches(
            protocol,
            provenance(
                ExperimentConfig(
                    experimental_evaluator=protocol.evaluator_version,
                )
            ),
        )
        if not checks["source_matches"]:
            issues.append("source_or_dependency_fingerprint_mismatch")
        from agent_reliability_lab.research.pilot_budget import ledgers

        with store.engine.connect() as connection:
            now = connection.scalar(sa.select(sa.func.clock_timestamp()))
            schema_exists = (
                connection.scalar(sa.select(sa.func.to_regclass("opsdesk_pilot.ledgers")))
                is not None
            )
            occupied = (
                schema_exists
                and connection.scalar(
                    sa.select(ledgers.c.ledger_id).where(ledgers.c.ledger_id == plan.ledger_id)
                )
                is not None
            )
            checks["ledger"] = "occupied" if occupied else "available_to_open"
            if occupied:
                issues.append("pilot_ledger_already_opened")
            price = plan.pricing.prices[0]
            if now < price.effective_from or (
                price.effective_until is not None and now >= price.effective_until
            ):
                issues.append("pricing_window_unavailable")
            largest = max(a.maximum_output_tokens for a in arms)
            if (
                plan.limits.maximum_usd
                < plan.price_ceiling(plan.limits.maximum_input_tokens, largest)
                or plan.limits.total_tokens < plan.limits.maximum_input_tokens + largest
                or min(plan.limits.total_calls, plan.limits.calls_per_scenario) < len(arms)
            ):
                issues.append("insufficient_pilot_capacity")
            if authorization_ref is not None:
                auth = store.get(authorization_ref)
                validate_authorization(store, auth, plan)
                checks["execution_mode"] = auth.mode
                checks["available_seconds"] = max(
                    0, min(plan.limits.duration_seconds, (auth.deadline - now).total_seconds())
                )
                if (
                    price.effective_until is not None
                    and (price.effective_until - now).total_seconds() <= checks["available_seconds"]
                ):
                    issues.append("price_expires_within_execution_window")
                issues.extend(auth.profile.incompatibilities(auth.mode))
                if auth.mode != "mock_http" and not checks["credential_configured"]:
                    issues.append("provider_credential_not_configured")
                if auth.mode == "groq_free" and checks["credential_configured"]:
                    checks["credential_matches"] = auth.profile.matches_credential(
                        os.environ.get("GROQ_API_KEY", "").strip()
                    )
                    if not checks["credential_matches"]:
                        issues.append("free_credential_binding_mismatch")
                try:
                    active_authorization(
                        connection, store.scope, authorization_ref, plan_ref.content_hash
                    )
                except ActivationBlocked as error:
                    issues.append(error.code)
    except ActivationBlocked as error:
        issues.append(error.code)
    except (ValueError, sa.exc.SQLAlchemyError):
        issues.append("references_or_database_unavailable")
    status = (
        "blocked"
        if issues
        else (
            "awaiting_operator_authorization"
            if authorization_ref is None
            else (
                "ready_for_mock_validation"
                if checks.get("execution_mode") == "mock_http"
                else "live_ready"
            )
        )
    )
    return dict(
        schema_version="live-preflight-1.0.0",
        status=status,
        checks=checks,
        issues=list(dict.fromkeys(issues)),
    )


def open_provider_pilot(
    store, plan_ref, protocol_ref, authorization_ref, mock_transport, activate_paid, activate_free
):
    import httpx2

    from agent_reliability_lab.research.groq_model import GroqHTTPModel
    from agent_reliability_lab.research.live_model import LiveHTTPModel
    from agent_reliability_lab.research.pilot_budget import PilotBudgetBroker

    require_disposable(store)
    plan = store.get(plan_ref)
    if plan.kind != "benchmark_pilot_plan" or plan.protocol != protocol_ref:
        raise ActivationBlocked("provider_pilot_protocol_mismatch")
    authority = store.get(authorization_ref)
    validate_authorization(store, authority, plan)
    groq = isinstance(authority.profile, GroqProfile)
    if authority.mode == "mock_http":
        if activate_paid or activate_free or not isinstance(mock_transport, httpx2.MockTransport):
            raise ActivationBlocked("offline_mock_transport_required")
        if groq and type(mock_transport) is not httpx2.MockTransport:
            raise ActivationBlocked("offline_mock_transport_required")
    elif groq:
        if not GROQ_FREE_NETWORK_ENABLED:
            raise ActivationBlocked("groq_external_activation_locked")
        if not activate_free or activate_paid or mock_transport is not None:
            raise ActivationBlocked("explicit_free_activation_required")
    elif (
        not activate_paid
        or activate_free
        or not PUBLIC_PROVIDER_NETWORK_ENABLED
        or mock_transport is not None
    ):
        raise ActivationBlocked(
            "external_activation_locked"
            if not PUBLIC_PROVIDER_NETWORK_ENABLED
            else "explicit_paid_activation_required"
        )
    readiness = preflight(store, plan_ref, authorization_ref)
    if readiness["status"] not in {"ready_for_mock_validation", "live_ready"}:
        raise ActivationBlocked(readiness["issues"][0])
    broker = PilotBudgetBroker(store.engine, store.scope, plan, authorization=authorization_ref)
    arms = validate_plan(store, plan)
    broker.initialize()
    broker.open(plan, arms)
    by_arm = {(arm.slot, arm.arm): arm for arm in arms}

    def make_model(run_ref, slot, arm, model_config):
        adapter = GroqHTTPModel if groq else LiveHTTPModel
        return adapter(
            broker, plan, by_arm[(slot, arm)], run_ref, model_config, authority, mock_transport
        )

    return authority, make_model


async def run_provider_pilot(
    store, authorization_ref, *, mock_transport=None, activate_paid=False, activate_free=False
):
    from agent_reliability_lab.research.benchmark import execute_benchmark
    from agent_reliability_lab.research.pilot import publish_pilot

    require_disposable(store)
    authority = store.get(authorization_ref)
    validate_authorization(store, authority)
    result_ref, _ = await execute_benchmark(
        store,
        authority.protocol,
        pilot_ref=authority.pilot,
        live_authorization=authorization_ref,
        mock_transport=mock_transport,
        activate_paid=activate_paid,
        activate_free=activate_free,
    )
    return publish_pilot(store, authority.pilot, result_ref)
