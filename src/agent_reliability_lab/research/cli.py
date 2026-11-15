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
        if result.kind == "benchmark_dataset" and any(
            c.partition == "held_out" for c in result.cases
        ):
            raise ValueError("held-out stimuli must remain in a sealed private catalog")
        print(result.model_dump_json(indent=2))
        return
    if args.command == "benchmark-guard":
        from agent_reliability_lab.research.heldout import guard_index

        guard_index()
        print('{"tracked_private_catalogs": false}')
        return
    if args.command == "benchmark-power":
        from agent_reliability_lab.research.cluster_design import plan_power
        from agent_reliability_lab.research.heldout_contracts import (
            ConfirmatoryProtocol,
            PowerDesign,
        )

        raw = args.file.read_bytes()
        if json.loads(raw).get("kind") == "benchmark_confirmatory_protocol":
            protocol = ConfirmatoryProtocol.model_validate_json(raw)
            report = plan_power(protocol.power, legacy=args.historical_cp13)
            from agent_reliability_lab.opsdesk.fixtures import digest

            report["protocol_hash"] = digest(protocol.model_dump(mode="json"))
            report["catalog"] = protocol.catalog.model_dump(mode="json")
        else:
            report = plan_power(PowerDesign.model_validate_json(raw), legacy=args.historical_cp13)
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    if args.command == "benchmark-heldout-audit" and not args.authorize_private_read:
        raise ValueError("private catalog access requires explicit authorization")
    if args.command == "benchmark-draft":
        from agent_reliability_lab.research.benchmark import starter_draft

        dataset, protocol = starter_draft(
            workspace=args.workspace, repetitions=args.repetitions, order_seed=args.seed
        )
        args.output.mkdir(parents=True, exist_ok=False)
        for name, artifact in (("dataset", dataset), ("protocol", protocol)):
            (args.output / f"{name}.json").write_text(
                artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
        return
    engine = engine_from_env()
    try:
        store = ResearchStore(engine, args.scope)
        if args.command == "init":
            await store.initialize()
            result = {"initialized": True, "scope": args.scope}
        elif args.command == "append":
            artifact = parse_artifact(json.loads(args.file.read_text(encoding="utf-8")))
            result = store.append(
                artifact,
                human_attestation=args.human_attestation,
                authorized_private_read=args.authorize_private_read,
            ).model_dump(mode="json")
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
        elif args.command in {"benchmark-run", "benchmark-verify"}:
            from agent_reliability_lab.research.benchmark import execute_benchmark, verify_result

            ref = Reference.model_validate_json(args.file.read_text(encoding="utf-8"))
            if args.command == "benchmark-run":
                allocation = (
                    Reference.model_validate_json(args.synthetic_allocation.read_bytes())
                    if args.synthetic_allocation
                    else None
                )
                frozen, _ = await execute_benchmark(store, ref, allocation_ref=allocation)
                result = frozen.model_dump(mode="json")
            else:
                store = ResearchStore(
                    engine.execution_options(postgresql_readonly=True), args.scope
                )
                artifact = store.get(ref)
                if artifact.kind != "benchmark_result":
                    raise ValueError("verification requires a frozen benchmark result")
                result = verify_result(store, artifact)
        elif args.command in {"benchmark-design-draft", "benchmark-heldout-audit"}:
            from agent_reliability_lab.research.heldout_contracts import PowerDesign
            from agent_reliability_lab.research.heldout_design import audit_registered, draft_design

            store = ResearchStore(engine.execution_options(postgresql_readonly=True), args.scope)
            ref = Reference.model_validate_json(args.file.read_bytes())
            if args.command == "benchmark-design-draft":
                power = (
                    PowerDesign.model_validate_json(args.power.read_bytes()) if args.power else None
                )
                records = draft_design(store, ref, args.identity, args.sha256, args.count, power)
                args.output.mkdir(parents=True, exist_ok=False)
                for name, artifact in records.items():
                    (args.output / f"{name}.json").write_text(
                        artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
                    )
                return
            result = audit_registered(store, ref, authorized=args.authorize_private_read)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["passed"] else 2
        elif args.command in {
            "benchmark-allocation-draft",
            "benchmark-preflight",
            "benchmark-confirmatory-analyze",
        }:
            store = ResearchStore(engine.execution_options(postgresql_readonly=True), args.scope)
            return confirmatory_command(store, args)
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


def confirmatory_command(store, args):
    from agent_reliability_lab.research.confirmatory import draft_allocation, preflight
    from agent_reliability_lab.research.confirmatory_analysis import (
        analysis_draft,
        analyze_allocation,
        verify_analysis,
    )
    from agent_reliability_lab.research.confirmatory_contracts import (
        EvidenceSelection,
        FutureBudget,
    )

    reference = Reference.model_validate_json(args.file.read_bytes())
    authorized = args.authorize_private_read
    status = 0
    if args.command == "benchmark-allocation-draft":
        budget = FutureBudget.model_validate_json(args.budget.read_bytes()) if args.budget else None
        artifact = draft_allocation(
            store,
            reference,
            identity=args.identity,
            count=args.clusters,
            repetitions=args.repetitions,
            target=args.target,
            budget=budget,
            synthetic=args.synthetic_development,
            authorized=authorized,
        )
        result = artifact.model_dump(mode="json")
    elif args.command == "benchmark-preflight":
        result = preflight(store, reference, authorized=authorized)
        status = 2 if result["status"] == "blocked" else 0
    elif reference.kind == "benchmark_confirmatory_analysis":
        if args.evidence or args.draft_identity:
            raise ValueError("registered analysis cannot be overridden")
        result = verify_analysis(store, store.get(reference), authorized=authorized)
    else:
        evidence = (
            EvidenceSelection.model_validate_json(args.evidence.read_bytes())
            if args.evidence
            else EvidenceSelection()
        )
        if args.draft_identity:
            result = analysis_draft(
                store, reference, evidence, args.draft_identity, authorized=authorized
            ).model_dump(mode="json")
        else:
            result = analyze_allocation(store, reference, evidence, authorized=authorized)
    print(json.dumps(result, indent=2, sort_keys=True))
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default="research")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Apply additive research migrations")
    draft = commands.add_parser("benchmark-draft", help="Write an editable synthetic CP12 draft")
    draft.add_argument("output", type=Path)
    draft.add_argument("--workspace", type=Path)
    draft.add_argument("--repetitions", type=int, default=2)
    draft.add_argument("--seed", type=int, default=42)
    commands.add_parser(
        "benchmark-guard", help="Check the Git index for sealed private catalog files"
    )
    power = commands.add_parser("benchmark-power", help="Simulate conditional cluster sample sizes")
    power.add_argument("file", type=Path)
    power.add_argument("--historical-cp13", action="store_true")
    design = commands.add_parser(
        "benchmark-design-draft",
        help="Create content-free CP13 records from a CP12 protocol reference",
    )
    design.add_argument("file", type=Path)
    design.add_argument("output", type=Path)
    design.add_argument("--identity", default="cp13_design")
    design.add_argument("--sha256", required=True)
    design.add_argument("--count", type=int, required=True)
    design.add_argument("--power", type=Path)
    audit = commands.add_parser(
        "benchmark-heldout-audit", help="Verify and audit sealed stimuli without executing"
    )
    audit.add_argument("file", type=Path)
    audit.add_argument("--authorize-private-read", action="store_true")
    for name in (
        "benchmark-allocation-draft",
        "benchmark-preflight",
        "benchmark-confirmatory-analyze",
    ):
        command = commands.add_parser(name)
        command.add_argument("file", type=Path)
        command.add_argument("--authorize-private-read", action="store_true")
        if name == "benchmark-allocation-draft":
            command.add_argument("--identity", default="cp14_allocation")
            command.add_argument("--clusters", type=int, required=True)
            command.add_argument("--repetitions", type=int, required=True)
            command.add_argument("--target", type=float, choices=(0.8, 0.9), default=0.8)
            command.add_argument("--budget", type=Path)
            command.add_argument("--synthetic-development", action="store_true")
        elif name == "benchmark-confirmatory-analyze":
            command.add_argument("--evidence", type=Path)
            command.add_argument("--draft-identity")
    for name in (
        "append",
        "validate",
        "review-status",
        "verify-pair",
        "verify-release",
        "analyze",
        "benchmark-run",
        "benchmark-verify",
    ):
        command = commands.add_parser(name)
        command.add_argument("file", type=Path)
        if name == "append":
            command.add_argument(
                "--human-attestation",
                action="store_true",
                help="Actual human submission only; identities remain unverified",
            )
            command.add_argument("--authorize-private-read", action="store_true")
        elif name == "benchmark-run":
            command.add_argument("--synthetic-allocation", type=Path)
        if name == "analyze":
            command.add_argument("--seed", type=int, default=0)
    command = commands.add_parser("list")
    command.add_argument("--kind")
    command.add_argument("--identity")
    args = parser.parse_args()
    try:
        status = asyncio.run(execute(args))
        if status:
            parser.exit(status)
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
