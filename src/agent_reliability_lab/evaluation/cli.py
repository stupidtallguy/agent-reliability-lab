"""Trusted evaluation CLI; no paid request without explicit live opt-in."""

import argparse
import asyncio
import json
from pathlib import Path

import sqlalchemy as sa

from agent_reliability_lab.evaluation import tables as t
from agent_reliability_lab.evaluation.contracts import ExperimentConfig, OracleSpec
from agent_reliability_lab.evaluation.reporting import export, report
from agent_reliability_lab.evaluation.runner import ScenarioRunner
from agent_reliability_lab.opsdesk.database import engine_from_env


def display(value) -> None:
    print(json.dumps(value, indent=2, default=str))


async def execute(args: argparse.Namespace) -> None:
    engine = engine_from_env()
    runner = ScenarioRunner(engine)
    try:
        await runner.store.initialize()
        if args.command == "run":
            config = (
                ExperimentConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
                if args.config
                else ExperimentConfig()
            )
            updates = {
                key: value
                for key, value in {
                    "repeats": args.repeat,
                    "transport": args.transport,
                    "source_commit": args.source_commit,
                }.items()
                if value is not None
            }
            payload = config.model_dump(mode="json")
            payload.update(updates)
            if args.provider:
                payload["model"]["provider"] = args.provider
            if args.model:
                payload["model"]["model_id"] = args.model
            config = ExperimentConfig.model_validate_json(json.dumps(payload))
            paths = (
                sorted(Path("benchmarks/development").glob("*.json"))
                if args.development
                else args.scenarios
            )
            experiment_id = await runner.run(paths, config, live=args.live)
            document = report(runner.store, experiment_id)
            display(
                {
                    "experiment_id": experiment_id,
                    "summary": document["summary"],
                    "trial_ids": [result["trial_id"] for result in document["results"]],
                    "export": str(export(document)),
                }
            )
            if any(
                result["status"] in {"infrastructure_failure", "invalid_scenario", "evidence_error"}
                for result in document["results"]
            ):
                raise RuntimeError("evaluation requires infrastructure/evidence review")
        elif args.command == "report":
            document = report(runner.store, args.experiment)
            display(
                {
                    "experiment_id": args.experiment,
                    "summary": document["summary"],
                    "export": str(export(document)),
                }
            )
        elif args.command == "score":
            oracle = (
                OracleSpec.model_validate_json(args.oracle.read_text(encoding="utf-8"))
                if args.oracle
                else None
            )
            display(runner.rescore(args.trial, oracle).model_dump(mode="json"))
        elif args.command == "inspect":
            trial = runner.store.trial(args.trial)
            if not args.evidence:
                trial.pop("evidence")
                trial.pop("scenario")
                trial["scores"] = [
                    score.model_dump(mode="json") for score in runner.store.scores(args.trial)
                ]
            display(trial)
        elif args.command == "cleanup":
            display(runner.cleanup(args.trial))
        elif args.experiment or args.scenario or args.execution:
            display(
                [
                    {
                        key: trial[key]
                        for key in (
                            "trial_id",
                            "experiment_id",
                            "scenario_id",
                            "trial_index",
                            "execution_id",
                            "state",
                            "cleanup",
                        )
                    }
                    for trial in runner.store.list_trials(
                        experiment_id=args.experiment,
                        scenario_id=args.scenario,
                        execution_id=args.execution,
                    )
                ]
            )
        else:
            with engine.connect() as connection:
                display(
                    [
                        dict(row)
                        for row in connection.execute(
                            sa.select(t.experiments.c.experiment_id, t.experiments.c.created_at)
                            .order_by(t.experiments.c.created_at.desc())
                            .limit(100)
                        ).mappings()
                    ]
                )
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("scenarios", nargs="*", type=Path)
    run.add_argument("--development", action="store_true")
    run.add_argument("--config", type=Path)
    run.add_argument("--repeat", type=int)
    run.add_argument("--provider", choices=("fake", "openai"))
    run.add_argument("--model")
    run.add_argument("--transport", choices=("stdio", "memory"))
    run.add_argument("--source-commit")
    run.add_argument("--live", action="store_true")
    item = commands.add_parser("report")
    item.add_argument("experiment")
    item = commands.add_parser("score")
    item.add_argument("trial")
    item.add_argument("--oracle", type=Path)
    item = commands.add_parser("inspect")
    item.add_argument("trial")
    item.add_argument("--evidence", action="store_true")
    item = commands.add_parser("cleanup")
    item.add_argument("trial")
    item = commands.add_parser("list")
    item.add_argument("--experiment")
    item.add_argument("--scenario")
    item.add_argument("--execution")
    args = parser.parse_args()
    if args.command == "run" and args.development and args.scenarios:
        parser.error("choose --development or scenario paths")
    try:
        asyncio.run(execute(args))
    except KeyboardInterrupt:
        parser.exit(130, "Evaluation interrupted; use list/inspect to review retained records.\n")
    except Exception as error:
        parser.exit(
            1,
            f"Evaluation command failed ({type(error).__name__}); "
            "inspect configuration/evidence.\n",
        )


if __name__ == "__main__":
    main()
