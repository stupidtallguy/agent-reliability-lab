"""Trusted developer workflow; registering records never fabricates human approval."""

import argparse
import asyncio
import json
from pathlib import Path

from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.research.analysis import analyze, compare_versions
from agent_reliability_lab.research.contracts import Pair, Reference, parse_artifact
from agent_reliability_lab.research.pairing import verify_pair
from agent_reliability_lab.research.persistence import ResearchStore


async def execute(args):
    if args.command == "validate":
        result = parse_artifact(json.loads(args.file.read_text(encoding="utf-8")))
        print(result.model_dump_json(indent=2))
        return
    engine = engine_from_env()
    try:
        store = ResearchStore(engine, args.scope)
        if args.command == "init":
            await store.initialize()
            result = {"initialized": True, "scope": args.scope}
        elif args.command == "append":
            artifact = parse_artifact(json.loads(args.file.read_text(encoding="utf-8")))
            result = store.append(artifact, human_attestation=args.human_attestation).model_dump(
                mode="json"
            )
        elif args.command == "list":
            result = store.list(args.kind, args.identity)
        elif args.command == "review-status":
            ref = Reference.model_validate_json(args.file.read_text(encoding="utf-8"))
            result = store.review_status(ref)
        elif args.command == "verify-release":
            from agent_reliability_lab.research.partitions import validate_release

            release = parse_artifact(json.loads(args.file.read_text(encoding="utf-8")))
            if release.kind != "dataset_release":
                raise ValueError("a composite dataset release is required")
            records = validate_release(store, release)
            result = dict(
                validation_version=release.validation_version,
                valid=True,
                development=sum(r.split == "development" for r in records),
                held_out=sum(r.split == "held_out" for r in records),
            )
        elif args.command == "verify-pair":
            pair = Pair.model_validate_json(args.file.read_text(encoding="utf-8"))
            result = verify_pair(
                store.evaluations, pair.baseline_trial_id, pair.guarded_trial_id, pair.oracle
            )
        else:
            spec = json.loads(args.file.read_text(encoding="utf-8"))
            pairs = [Reference.model_validate(ref) for ref in spec["pairs"]]
            split = Reference.model_validate(spec["split"])
            if "evaluator_versions" in spec:
                result = compare_versions(
                    store,
                    pairs,
                    split,
                    spec["evaluator_versions"],
                    policy=spec.get("comparison_policy"),
                    score_selections=spec.get("score_selections"),
                    seed=args.seed,
                )
            else:
                result = analyze(
                    store,
                    pairs,
                    split,
                    spec["evaluator_version"],
                    score_selections=spec.get("score_selections"),
                    seed=args.seed,
                )
        print(json.dumps(result, indent=2, default=str, sort_keys=True))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default="research")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Apply additive research migrations")
    for name in ("append", "validate", "review-status", "verify-pair", "verify-release", "analyze"):
        command = commands.add_parser(name)
        command.add_argument("file", type=Path)
        if name == "append":
            command.add_argument(
                "--human-attestation",
                action="store_true",
                help="Actual human submission only; identities remain unverified",
            )
        if name == "analyze":
            command.add_argument("--seed", type=int, default=0)
    command = commands.add_parser("list")
    command.add_argument("--kind")
    command.add_argument("--identity")
    args = parser.parse_args()
    try:
        asyncio.run(execute(args))
    except Exception as error:
        if getattr(error, "code", None):
            import sys

            print(
                json.dumps(dict(code=error.code, exclusions=getattr(error, "exclusions", []))),
                file=sys.stderr,
            )
        parser.exit(
            1,
            f"Research command failed ({type(error).__name__}); "
            "inspect frozen references and configuration.\n",
        )
