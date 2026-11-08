"""Trusted developer host. Live requests always require explicit opt-in."""

import argparse
import asyncio
import json
import uuid

from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
from agent_reliability_lab.agent.demo import CASES, demo_plan
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.opsdesk.fixtures import baseline_access, load_baseline


def display(value) -> None:
    print(json.dumps(value, indent=2, default=str))


async def execute(args: argparse.Namespace) -> None:
    engine = engine_from_env()
    host = AgentExecution(engine)
    manager = SandboxManager(engine)
    disposable = None
    result = None
    try:
        if args.command in {"journal", "result", "resume"}:
            uuid.UUID(args.execution)
            row = host.store.get(args.execution)
            if args.command == "journal":
                display(host.store.trace(args.execution))
                return
            if args.command == "result":
                display(row["result"])
                return
            config = AgentConfig.model_validate(row["config"])
            if config.model.provider == "openai" and not args.live:
                raise ValueError("resuming a real model requires --live")
            execution_id = args.execution
        else:
            if args.provider == "openai" and (not args.live or not args.model):
                raise ValueError("OpenAI requires both --live and an explicit --model ID")
            task, actor, script = demo_plan(args.case)
            if args.command == "demo":
                # Never open, reset or clean an existing sandbox for this command.
                disposable = "agent_demo_" + uuid.uuid4().hex[:20]
                manager.provision(disposable, load_baseline(), baseline_access())
                run_id = disposable
            else:
                task, actor, run_id = args.task, args.actor, args.run
            config = AgentConfig(
                sandbox_run_id=run_id,
                actor_id=actor,
                tenant_id="opsdesk" if args.command == "demo" else args.tenant,
                model=ModelConfig(
                    provider=args.provider,
                    model_id=args.model or "scripted-v1",
                    script=script if args.provider == "fake" else [],
                ),
            )
            execution_id = await host.create(task, config)
            display(
                {
                    "execution_id": execution_id,
                    "sandbox": run_id,
                    "provider": args.provider,
                    "scripted_case": args.case,
                }
            )
        result = await host.run(
            execution_id, config, live_opt_in=args.live, pause_before_tools=args.pause_before_tools
        )
        display(result.model_dump(mode="json"))
        if args.command == "demo" and not args.pause_before_tools:
            expected = {"viewer_denied": "permission_denied", "error": "tool_failed"}.get(
                args.case, "completed"
            )
            if result.status != expected:
                raise RuntimeError("demonstration did not reach its expected terminal status")
    finally:
        if disposable and result is not None and not result.resume_eligible:
            manager.cleanup(disposable)
        elif disposable:
            display(
                {
                    "retained_sandbox": disposable,
                    "reason": "Keep interrupted or uncertain state for inspection/resume.",
                }
            )
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("ask", "demo"):
        item = commands.add_parser(command)
        item.add_argument("--provider", choices=("fake", "openai"), default="fake")
        item.add_argument("--model", help="Exact provider model ID; no fallback")
        item.add_argument("--live", action="store_true", help="Opt in to paid provider requests")
        item.add_argument(
            "--case",
            choices=CASES,
            default="order",
            help="Fixed fake plan; fake does not interpret arbitrary task text",
        )
        item.add_argument("--pause-before-tools", action="store_true")
        if command == "ask":
            item.add_argument("task")
            item.add_argument("--run", required=True)
            item.add_argument("--actor", required=True)
            item.add_argument("--tenant", default="opsdesk")
    for command in ("resume", "journal", "result"):
        item = commands.add_parser(command)
        item.add_argument("execution")
        if command == "resume":
            item.add_argument("--live", action="store_true")
            item.add_argument("--pause-before-tools", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(execute(args))
    except Exception as error:
        # No raw SDK/database messages or connection strings on the console.
        parser.exit(1, f"Agent command failed ({type(error).__name__}); inspect configuration.\n")


if __name__ == "__main__":
    main()
