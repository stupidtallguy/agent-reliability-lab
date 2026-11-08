"""Trusted execution host, durable identity and monotonic active-segment timing."""

import asyncio
import secrets
import time

from langsmith import tracing_context
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from agent_reliability_lab.adversarial.defenses import GUARDED_POLICY
from agent_reliability_lab.agent.config import AgentConfig
from agent_reliability_lab.agent.errors import BudgetExceeded, ContextMismatch, ExecutionInterrupted
from agent_reliability_lab.agent.graph import SYSTEM_POLICY, GraphRuntime
from agent_reliability_lab.agent.models.base import ModelAdapter
from agent_reliability_lab.agent.models.fake import ScriptedModel
from agent_reliability_lab.agent.models.openai import OpenAIModel
from agent_reliability_lab.agent.persistence import ExecutionStore, utcnow
from agent_reliability_lab.agent.state import TERMINAL, AgentResult
from agent_reliability_lab.agent.tool_adapter import ToolSession
from agent_reliability_lab.mcp.context import BoundContext, LaunchConfig
from agent_reliability_lab.opsdesk.fixtures import digest


class AgentExecution:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.store = ExecutionStore(engine)

    def launch(self, config: AgentConfig) -> LaunchConfig:
        return LaunchConfig(
            run_id=config.sandbox_run_id,
            actor_id=config.actor_id,
            tenant_id=config.tenant_id,
            signing_key=SecretStr(secrets.token_hex(32)),
        )

    async def create(self, task: str, config: AgentConfig) -> str:
        if not task.strip() or len(task) > 8000:
            raise ValueError("task must contain 1-8000 characters")
        await self.store.initialize()
        binding = BoundContext.bind(self.engine, self.launch(config))
        return self.store.create(
            config, {"marker": binding.marker, "seed_hash": binding.seed_hash}, task
        )

    async def run(
        self,
        execution_id: str,
        config: AgentConfig,
        *,
        model: ModelAdapter | None = None,
        live_opt_in: bool = False,
        pause_before_tools: bool = False,
        after_dispatch=None,
    ) -> AgentResult:
        with self.store.claim(execution_id):
            row = self.store.get(execution_id)
            if digest(config.model_dump(mode="json")) != row["config_hash"]:
                raise ContextMismatch(
                    "execution host configuration differs from the persisted configuration"
                )
            if row["status"] in TERMINAL:
                return AgentResult.model_validate(row["result"])
            launch = self.launch(config)
            binding = BoundContext.bind(self.engine, launch)
            if row["context"] != {"marker": binding.marker, "seed_hash": binding.seed_hash}:
                raise ContextMismatch("sandbox was reset, replaced or changed; resume rejected")
            self.store.redactor.values.append(launch.signing_key.get_secret_value())
            if row["status"] == "running":
                self.store.update(execution_id, timing_complete=False)
            self.store.update(execution_id, status="running")
            base = row["elapsed_ms"]
            started = time.perf_counter()

            def clock() -> float:
                return base + (time.perf_counter() - started) * 1000

            self.store.event(
                execution_id,
                "run_started" if row["status"] == "prepared" else "run_resumed",
                clock(),
                thread_id=row["thread_id"],
                sandbox_run_id=config.sandbox_run_id,
                actor_reference=config.actor_id,
                provider=config.model.provider,
                model=config.model.model_id,
            )
            owned = model is None
            provider = model
            checkpoint_id = None
            state = {
                "execution_id": execution_id,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_POLICY
                        + (
                            GUARDED_POLICY
                            if config.defense and config.defense.configuration == "guarded"
                            else ""
                        ),
                    },
                    {"role": "user", "content": row["task"]},
                ],
                "turn": 0,
                "decision": {},
                "pending": [],
                "cursor": 0,
                "status": "running",
                "reason": None,
                "answer": "",
                "declared_complete": None,
                "response_completed": False,
                "tool_errors": False,
                "denied": False,
                "retry": False,
            }
            try:
                remaining = min(
                    (row["deadline"] - utcnow()).total_seconds(),
                    config.budgets.max_wall_seconds - clock() / 1000,
                )
                if remaining <= 0:
                    raise BudgetExceeded("wall_clock")
                if provider is None:
                    provider = (
                        ScriptedModel(config.model)
                        if config.model.provider == "fake"
                        else OpenAIModel(config.model.model_id, live_opt_in=live_opt_in)
                    )
                # The lifecycle lease prevents reset/cleanup while any model/tool call is active.
                with binding.sandbox.transaction() as (_, registry), tracing_context(enabled=False):
                    if registry["marker"] != binding.marker:
                        raise ContextMismatch("sandbox changed before execution")
                    async with (
                        asyncio.timeout(remaining),
                        ToolSession(self.engine, launch, config) as session,
                        self.store.checkpointer() as saver,
                    ):
                        runtime = GraphRuntime(
                            self.store,
                            row,
                            config,
                            provider,
                            session,
                            clock,
                            after_dispatch=after_dispatch,
                        )
                        available = set(registry["tool_access"]["available"])
                        if config.allowed_tools is not None:
                            available.intersection_update(config.allowed_tools)
                        runtime.catalog = [
                            tool for tool in session.catalog if tool["name"] in available
                        ]
                        graph = runtime.build(saver, pause_before_tools=pause_before_tools)
                        graph_config = {
                            "configurable": {"thread_id": row["thread_id"]},
                            "recursion_limit": config.budgets.max_graph_steps + 10,
                        }
                        snapshot = await graph.aget_state(graph_config)
                        state = await graph.ainvoke(
                            None if snapshot.values else state, graph_config, durability="sync"
                        )
                        snapshot = await graph.aget_state(graph_config)
                        checkpoint_id = snapshot.config["configurable"].get("checkpoint_id")
                        if snapshot.next and state["status"] == "running":
                            state.update(status="interrupted", reason="host_pause_before_tools")
            except (BudgetExceeded, TimeoutError):
                self.store.event(execution_id, "budget_exhausted", clock(), reason="wall_clock")
                state.update(
                    status="budget_exhausted",
                    reason="wall_clock",
                    answer="Execution stopped at the wall-clock budget.",
                )
            except (ExecutionInterrupted, asyncio.CancelledError, KeyboardInterrupt):
                state.update(
                    status="interrupted",
                    reason="execution_interrupted",
                    answer="Execution was interrupted; inspect and resume using its ID.",
                )
            except Exception:
                state.update(
                    status="failed",
                    reason="execution_error",
                    answer="Execution stopped after an internal error.",
                )
            finally:
                if owned and isinstance(provider, OpenAIModel):
                    await provider.close()
            if checkpoint_id is None:
                async with self.store.checkpointer() as saver:
                    checkpoint = await saver.aget_tuple(
                        {"configurable": {"thread_id": row["thread_id"]}}
                    )
                    if checkpoint:
                        checkpoint_id = checkpoint.config["configurable"]["checkpoint_id"]
            current = self.store.get(execution_id)
            result = AgentResult(
                execution_id=execution_id,
                thread_id=row["thread_id"],
                status=state["status"],
                answer=self.store.redactor.text(state["answer"]),
                response_completed=state["response_completed"],
                agent_declared_completion=state["declared_complete"],
                tool_call_count=current["tool_calls"],
                llm_call_count=current["llm_calls"],
                graph_step_count=current["graph_steps"],
                duration_seconds=clock() / 1000,
                timing_complete=current["timing_complete"],
                usage=self.store.usage(execution_id),
                reason=state["reason"],
                resume_eligible=state["status"] == "interrupted",
                checkpoint_id=checkpoint_id,
                trace_reference=f"opsdesk-agent://executions/{execution_id}/journal",
            )
            self.store.finish_run(result)
            return result
