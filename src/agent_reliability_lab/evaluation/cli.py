"""Trusted evaluation CLI; no paid request without explicit live opt-in."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

import sqlalchemy as sa

from agent_reliability_lab.adversarial.reporting import compare
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
                    "defense": args.defense,
                    "experimental_evaluator": args.experimental_evaluator,
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
            if args.suite:
                kinds = ("faults", "attacks", "controls") if args.suite == "all" else (args.suite,)
                paths = [
                    path
                    for kind in kinds
                    for path in sorted(Path(f"benchmarks/{kind}/development").glob("*.json"))
                ]
                if not args.config:
                    config = ExperimentConfig.model_validate_json(
                        Path("benchmarks/evaluation/checkpoint5.json").read_text()
                    )
                    revised = config.model_dump(mode="json")
                    revised.update(updates)
                    if args.provider:
                        revised["model"]["provider"] = args.provider
                    if args.model:
                        revised["model"]["model_id"] = args.model
                    config = ExperimentConfig.model_validate_json(json.dumps(revised))
            if args.paired:
                pairing_id = uuid.uuid4().hex
                ids = []
                invalid = False
                for variant in ("baseline", "guarded"):
                    paired = config.model_copy(
                        update={"defense": variant, "pairing_id": pairing_id}
                    )
                    identifier = await runner.run(paths, paired, live=args.live)
                    ids.append(identifier)
                    document = report(runner.store, identifier)
                    invalid = invalid or any(
                        result["status"]
                        in {"infrastructure_failure", "invalid_scenario", "evidence_error"}
                        for result in document["results"]
                    )
                    display(
                        {
                            "experiment_id": identifier,
                            "configuration": variant,
                            "export": str(export(document)),
                        }
                    )
                comparison = compare(runner.store, *ids)
                # Comparison is an immutable companion artifact, not another trial.
                destination = Path("artifacts/evaluations/pairs") / pairing_id
                destination.mkdir(parents=True, exist_ok=False)
                (destination / "comparison.json").write_text(
                    json.dumps(comparison, indent=2), encoding="utf-8"
                )
                display(comparison)
                if invalid:
                    raise RuntimeError("paired evaluation requires infrastructure/evidence review")
                return
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
        elif args.command == "compare":
            display(compare(runner.store, args.baseline, args.guarded))
        elif args.command == "report":
            versions = getattr(args, "compare_evaluators", None)
            if versions:
                documents = [
                    report(runner.store, args.experiment, evaluator_version=v) for v in versions
                ]
                display(
                    {
                        "comparison": "separate_version_cohorts",
                        "warning": "Incompatible scoring semantics; no pooled metrics.",
                        "reports": [
                            {
                                "evaluator_version": v,
                                "summary": d["summary"],
                                "export": str(export(d)),
                            }
                            for v, d in zip(versions, documents, strict=True)
                        ],
                    }
                )
                return
            document = report(
                runner.store,
                args.experiment,
                evaluator_version=getattr(args, "evaluator_version", None),
                scoring_ids=getattr(args, "score_id", None),
                trial_ids=getattr(args, "trial_id", None),
            )
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
            display(
                runner.rescore(
                    args.trial, oracle, experimental_evaluator=args.experimental_evaluator
                ).model_dump(mode="json")
            )
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
    run.add_argument("--suite", choices=("all", "faults", "attacks", "controls"))
    run.add_argument("--defense", choices=("baseline", "guarded"))
    run.add_argument("--paired", action="store_true")
    run.add_argument(
        "--experimental-evaluator", choices=("1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0")
    )
    item = commands.add_parser("compare")
    item.add_argument("baseline")
    item.add_argument("guarded")
    item = commands.add_parser("report")
    item.add_argument("experiment")
    item.add_argument("--evaluator-version")
    item.add_argument("--score-id", action="append")
    item.add_argument("--trial-id", action="append")
    item.add_argument("--compare-evaluators", nargs="+")
    item = commands.add_parser("score")
    item.add_argument("trial")
    item.add_argument("--oracle", type=Path)
    item.add_argument(
        "--experimental-evaluator", choices=("1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0")
    )
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
    if args.command == "run" and args.suite and (args.scenarios or args.development):
        parser.error("choose --suite or scenario paths/--development")
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
