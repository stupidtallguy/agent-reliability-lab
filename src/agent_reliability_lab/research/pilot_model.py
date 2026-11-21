"""Broker-gated, in-process simulation of the existing OpenAI wire and response parser."""

import asyncio
import json
import time
from types import SimpleNamespace

import sqlalchemy as sa
from openai.types.chat import ChatCompletion

from agent_reliability_lab.agent.errors import ModelFailure
from agent_reliability_lab.agent.journal import Redactor
from agent_reliability_lab.agent.models.fake import ScriptedModel
from agent_reliability_lab.agent.models.openai import parse_completion, request_completion
from agent_reliability_lab.agent.persistence import ExecutionStore
from agent_reliability_lab.agent.provenance import verify
from agent_reliability_lab.evaluation.tables import experiments, trials
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.pilot_contracts import CallRequest, ProviderObservation


def reply_fingerprint(reply):
    return digest(
        {
            "answer": reply["answer"],
            "calls": [
                {key: call[key] for key in ("call_id", "name", "arguments_json")}
                for call in reply["calls"]
            ],
            "declared_complete": reply["declared_complete"],
        }
    )


class BoundPilotModel:
    def __init__(self, broker, plan, arm, run_ref, model_config):
        self.broker, self.plan, self.arm, self.run_ref = broker, plan, arm, run_ref
        self.model_config = model_config
        self.store = ExecutionStore(broker.engine)

    async def decide(self, messages, tools, turn, max_output_tokens):
        raise ModelFailure("pilot_requires_durable_model_request")

    def _validate_execution(self, execution_id, config):
        query = (
            sa.select(
                trials.c.scenario_id,
                trials.c.sandbox_run_id,
                experiments.c.manifest,
                experiments.c.manifest_hash,
            )
            .join(experiments, experiments.c.experiment_id == trials.c.experiment_id)
            .where(trials.c.execution_id == execution_id)
        )
        with self.broker.engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        capture = row["manifest"].get("benchmark", {}) if row is not None else {}
        if (
            row is None
            or digest(row["manifest"]) != row["manifest_hash"]
            or row["sandbox_run_id"] != config["sandbox_run_id"]
            or row["scenario_id"] != self.arm.scenario
            or capture.get("run") != self.run_ref.model_dump(mode="json")
            or capture.get("protocol") != self.plan.protocol.model_dump(mode="json")
            or capture.get("schedule_hash") != self.plan.schedule_hash
            or capture.get("arm") != self.arm.arm
            or capture.get("slot", {}).get("slot") != self.arm.slot
        ):
            raise ModelFailure("pilot_trial_allocation_mismatch")

    def _bound_request(
        self, execution_id, request_id, messages, tools, turn, max_output_tokens, **extra
    ):
        input_hash = digest([messages, tools])
        execution = self.store.get(execution_id)
        config = execution["config"]
        if (
            execution["status"] != "running"
            or execution["config_hash"] != digest(config)
            or config["tenant_id"] != self.arm.tenant
            or config["actor_id"] != self.arm.actor
            or digest(config["model"]) != self.arm.script_config_hash
            or digest(self.model_config.model_dump(mode="json")) != self.arm.script_config_hash
        ):
            raise ModelFailure("pilot_execution_configuration_mismatch")
        self._validate_execution(execution_id, config)
        records = self.store.provenance(execution_id)
        verify(records, execution_id)
        starts = [
            record["body"]
            for record in records
            if record["kind"] == "model_started" and record["reference"] == request_id
        ]
        if (
            len(starts) != 1
            or any(
                starts[0].get(key) != value
                for key, value in dict(
                    request_id=request_id,
                    execution_id=execution_id,
                    input_hash=input_hash,
                    turn=turn,
                    provider=self.model_config.provider,
                    model=self.model_config.model_id,
                ).items()
            )
            or starts[0]["context"].get("max_output_tokens") != max_output_tokens
        ):
            raise ModelFailure("pilot_sealed_request_mismatch")
        # This number is an offline fixture observation only. The independent upper
        # bound in the budget manifest determines reservation capacity.
        estimate = len(json.dumps([messages, tools], ensure_ascii=False).encode("utf-8"))
        return CallRequest(
            attempt_id=request_id,
            execution_id=execution_id,
            allocation=self.arm,
            turn=turn,
            model_config_hash=digest(self.plan.model.model_dump(mode="json")),
            pricing_hash=self.plan.pricing_hash,
            input_hash=input_hash,
            estimated_input_tokens=estimate,
            maximum_output_tokens=max_output_tokens,
            **extra,
        )


class OfflinePilotModel(BoundPilotModel):
    def __init__(self, broker, plan, arm, run_ref, script_config):
        if plan.mode != "offline_fixture" or script_config.provider != "fake":
            raise ValueError("live pilot execution is disabled")
        super().__init__(broker, plan, arm, run_ref, script_config)
        self.script = ScriptedModel(script_config)

    async def decide_for_request(
        self, execution_id, request_id, messages, tools, turn, max_output_tokens
    ):
        request = self._bound_request(
            execution_id, request_id, messages, tools, turn, max_output_tokens
        )
        self.broker.reserve(request)
        dispatch_started = time.monotonic()
        remaining = self.broker.begin_dispatch(request)
        if remaining is None:
            raise ModelFailure("pilot_attempt_already_dispatched")
        started = time.perf_counter()
        transport = FixtureChat(self, request)
        client = SimpleNamespace(chat=SimpleNamespace(completions=transport))
        try:
            timeout = remaining - (time.monotonic() - dispatch_started)
            if timeout <= 0:
                raise ModelFailure("pilot_experiment_deadline")
            async with asyncio.timeout(timeout):
                response = await request_completion(
                    client, self.plan.model.model_id, messages, tools, max_output_tokens
                )
        except (Exception, asyncio.CancelledError):
            self.broker.mark_uncertain(request)
            raise
        usage = response.usage
        try:
            decision = parse_completion(response)
            decision.declared_complete = transport.declared_complete
            reply_hash = reply_fingerprint(Redactor().clean(decision.model_dump(mode="json")))
        except (ModelFailure, ValueError):
            self.broker.observe(request, _observation(response, usage, "failed", None, started))
            raise ModelFailure("invalid_pilot_response") from None
        state = self.broker.observe(
            request, _observation(response, usage, "completed", reply_hash, started)
        )["state"]
        if state == "breached":
            raise ModelFailure("pilot_provider_bound_breach")
        return decision


def _observation(response, usage, outcome, reply_hash, started):
    return ProviderObservation(
        outcome=outcome,
        reported_model=response.model,
        provider_request_id=response._request_id,
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        response_hash=reply_hash,
    )


class FixtureChat:
    """No network client, endpoint, credential, SDK retry, or external side effect."""

    def __init__(self, model, request):
        self.model, self.request = model, request
        self.declared_complete = None

    async def create(self, *, model, messages, max_completion_tokens, store, **options):
        request = self.request
        first = request.allocation.slot == "slot_0001" and request.turn == 0
        fault = self.model.plan.fixture_fault
        if first and fault == "first_dispatch_timeout":
            raise ModelFailure("model_timeout", True)
        decision = await self.model.script.decide(
            messages, options.get("tools", []), request.turn, max_completion_tokens
        )
        self.declared_complete = decision.declared_complete
        inputs = decision.usage.input_tokens if decision.usage.input_tokens is not None else 8
        outputs = decision.usage.output_tokens if decision.usage.output_tokens is not None else 4
        identifier = "fixture-" + request.attempt_id
        response = ChatCompletion.model_validate(
            dict(
                id=identifier,
                model=model,
                created=0,
                object="chat.completion",
                choices=[
                    dict(
                        index=0,
                        finish_reason="tool_calls" if decision.calls else "stop",
                        message=dict(
                            role="assistant",
                            content=decision.answer,
                            tool_calls=[
                                dict(
                                    type="function",
                                    id=call.call_id,
                                    function=dict(name=call.name, arguments=call.arguments_json),
                                )
                                for call in decision.calls
                            ],
                        ),
                    )
                ],
                usage=None
                if first and fault == "first_usage_missing"
                else dict(
                    prompt_tokens=inputs, completion_tokens=outputs, total_tokens=inputs + outputs
                ),
            )
        )
        response._request_id = identifier
        return response
