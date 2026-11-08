"""Trusted developer administration, never exposed as an agent tool."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from agent_reliability_lab.opsdesk.database import SandboxManager, engine_from_env
from agent_reliability_lab.opsdesk.fixtures import (
    baseline_access,
    from_scenario,
    load_baseline,
    load_scenario,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpsDesk synthetic sandbox administration")
    parser.add_argument(
        "command", choices=["provision", "migrate", "inspect", "verify", "reset", "cleanup"]
    )
    parser.add_argument("--run", required=True, help="safe run identifier, e.g. demo_01")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scenario", type=Path)
    source.add_argument("--baseline", action="store_true")
    parser.add_argument(
        "--benchmark", action="store_true", help="inspect legacy v1 domain projection"
    )
    args = parser.parse_args()
    if args.command == "provision" and not (args.scenario or args.baseline):
        parser.error("provision requires --scenario PATH or --baseline")
    if args.command != "provision" and (args.scenario or args.baseline):
        parser.error(
            "fixture options are only accepted for provision; reset uses the stored original"
        )
    engine = None
    try:
        engine = engine_from_env()
        manager = SandboxManager(engine)
        if args.command == "provision":
            if args.scenario:
                scenario = load_scenario(args.scenario)
                seed, access = from_scenario(scenario), scenario.tools
            else:
                seed, access = load_baseline(), baseline_access()
            manager.provision(args.run, seed, access)
            print(f"Provisioned {args.run}; migrations applied and fixture loaded atomically.")
        elif args.command == "cleanup":
            manager.cleanup(args.run)
            print(f"Cleaned up registered sandbox {args.run}.")
        else:
            sandbox = manager.open(args.run)
            if args.command == "inspect":
                print(
                    json.dumps(sandbox.snapshot(benchmark=args.benchmark), indent=2, sort_keys=True)
                )
            elif args.command == "verify":
                if not sandbox.verify():
                    print("Logical state differs from the initial fixture.", file=sys.stderr)
                    return 1
                print("Fixture hash and original logical state verified.")
            elif args.command == "reset":
                sandbox.reset()
                print("Original logical state restored and verified.")
            else:
                sandbox.apply_migrations()
                print("Sandbox is at the current Alembic revision.")
        return 0
    except (ValueError, ValidationError, OSError) as error:
        # Validation errors are safe, but omit input values which may include configuration secrets.
        print(
            f"Sandbox command rejected ({type(error).__name__}). "
            "Check run, fixture and configuration.",
            file=sys.stderr,
        )
        return 2
    except SQLAlchemyError:
        print(
            "Database operation failed; transaction rolled back. "
            "Check connectivity and migrations.",
            file=sys.stderr,
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
