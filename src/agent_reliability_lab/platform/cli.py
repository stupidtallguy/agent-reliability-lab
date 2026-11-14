"""Safe local product entry points, separate from the read-only dashboard."""

import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from agent_reliability_lab import __version__
from agent_reliability_lab.opsdesk.database import make_engine
from agent_reliability_lab.platform.containers import compose, inspect_owned
from agent_reliability_lab.platform.demo import assets, prepare_demo

DEMO_URL = "postgresql+psycopg://opsdesk_demo@127.0.0.1:55435/opsdesk_lab_test"


def run_command(command, **options):
    result = subprocess.run(command, capture_output=True, text=True, **options)
    if result.returncode:
        raise RuntimeError(
            f"Command failed: {Path(command[0]).name}; inspect local installation "
            f"and resource ownership"
        )
    return result.stdout


def inspect_demo(required=False):
    info = inspect_owned("opsdesk-demo", "55435")
    if required and info is None:
        raise RuntimeError("Owned demo container is unavailable")
    return info


def start_demo():
    inspect_demo()
    command = compose(assets(), "opsdesk-demo", "compose.demo.yaml")
    run_command(command + ["config", "--quiet"])
    run_command(command + ["up", "-d", "--wait", "postgres"])
    inspect_demo(required=True)


def launch_dashboard(port=8501, *, url=None, scope=None, browser=True):
    if not 1024 <= port <= 65535:
        raise ValueError("dashboard port must be between 1024 and 65535")
    if importlib.util.find_spec("streamlit") is None:
        raise RuntimeError("Install the stack extra: uv sync --locked --extra stack")
    from agent_reliability_lab.dashboard.design import streamlit_theme

    environment = {**os.environ, **streamlit_theme()}
    if url:
        environment["OPSDESK_DASHBOARD_DATABASE_URL"] = url
    if scope:
        environment["OPSDESK_DASHBOARD_SCOPE"] = scope
    address = f"http://127.0.0.1:{port}"
    print("Read-only dashboard:", address, flush=True)
    target = Path(__file__).parents[1] / "dashboard/app.py"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(target),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "false" if browser else "true",
        "--browser.serverAddress",
        "127.0.0.1",
        "--browser.gatherUsageStats",
        "false",
    ]
    try:
        return subprocess.call(command, env=environment)
    except KeyboardInterrupt:
        return 130


def doctor():
    dependencies = {}
    for name in ["agent-reliability-lab", "langgraph", "mcp", "psycopg", "streamlit"]:
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = None
    docker = shutil.which("docker") is not None
    running = False
    if docker:
        running = (
            subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=15,
            ).returncode
            == 0
        )
    return dict(
        python=sys.version.split()[0],
        supported_python=sys.version_info[:2] in {(3, 11), (3, 12)},
        dependencies=dependencies,
        docker_cli=docker,
        docker_engine=running,
        uv_cli=shutil.which("uv") is not None,
        dashboard_configured=bool(os.environ.get("OPSDESK_DASHBOARD_DATABASE_URL")),
        paid_api_required=False,
    )


def review_workspace(destination):
    from agent_reliability_lab.research.contracts import (
        Adjudication,
        AnalysisRecord,
        Attestation,
        DatasetRelease,
        Oracle,
        Preregistration,
        Reviewer,
        SplitManifest,
    )

    destination.mkdir(parents=True, exist_ok=False)
    for model in [
        Oracle,
        Reviewer,
        Attestation,
        Adjudication,
        SplitManifest,
        DatasetRelease,
        Preregistration,
        AnalysisRecord,
    ]:
        (destination / (model.__name__ + ".schema.json")).write_text(
            json.dumps(model.model_json_schema(), indent=2), encoding="utf-8"
        )
    (destination / "REVIEW.md").write_text(
        (
            "# Independent human review workspace\n\nNo review, registration or "
            "approval is created by this export.\n\n1. Obtain the exact frozen "
            "oracle/reference hash from the research CLI.\n2. Independently "
            "review legitimate behavior, prohibited behavior, executable "
            "rules, exposure requirements, unknown states and denominators.\n3."
            " Declare identity, role and conflicts. Identities remain "
            "externally unverified.\n4. Submit actual attestations through the "
            "trusted research CLI with explicit human-attestation opt-in.\n5. "
            "Preserve disagreements; independent adjudication must pin current"
            " review hashes.\n6. Independently author held-out families, then "
            "validate one composite dataset release.\n7. Author sample-size "
            "rationale, missing-data rules and preregistration before "
            "authorized execution.\n"
        ),
        encoding="utf-8",
    )
    return dict(workspace=str(destination), registrations_created=0, human_approvals_created=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    test = commands.add_parser("test")
    test.add_argument("--unit-only", action="store_true")
    test.add_argument("--workspace", type=Path)
    commands.add_parser("stop-tests")
    for name in ("demo", "reliability-demo"):
        demo = commands.add_parser(name)
        demo.add_argument("--workspace", type=Path)
        demo.add_argument("--output", type=Path, default=Path("artifacts/evaluations"))
        demo.add_argument("--no-ui", action="store_true")
        demo.add_argument("--port", type=int, default=8501)
        if name == "demo":
            demo.add_argument("--source-commit")
    dash = commands.add_parser("dashboard")
    dash.add_argument("--port", type=int, default=8501)
    dash.add_argument("--no-browser", action="store_true")
    workspace = commands.add_parser("review-workspace")
    workspace.add_argument("output", type=Path)
    stop = commands.add_parser("stop-demo")
    stop.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    try:
        if args.command in {"test", "stop-tests"}:
            from agent_reliability_lab.platform.testing import run_tests

            raise SystemExit(
                run_tests(
                    getattr(args, "workspace", None) or Path.cwd(),
                    unit_only=getattr(args, "unit_only", False),
                    stop=args.command == "stop-tests",
                )
            )
        elif args.command == "doctor":
            print(json.dumps(doctor(), indent=2))
        elif args.command == "review-workspace":
            print(json.dumps(review_workspace(args.output), indent=2))
        elif args.command == "dashboard":
            raise SystemExit(launch_dashboard(args.port, browser=not args.no_browser))
        elif args.command == "stop-demo":
            inspect_demo(required=True)
            run_command(
                compose(assets(), "opsdesk-demo", "compose.demo.yaml") + ["down", "postgres"]
            )
            print("Owned temporary demo stopped. Exported evidence reports remain on disk.")
        else:
            root = assets(args.workspace)
            start_demo()
            engine = make_engine(DEMO_URL, allow_sandbox=True)
            try:
                if args.command == "reliability-demo":
                    from agent_reliability_lab.reliability.demo import prepare_reliability_demo

                    result = asyncio.run(prepare_reliability_demo(engine, args.output))
                else:
                    result = asyncio.run(
                        prepare_demo(engine, root, args.output, source_commit=args.source_commit)
                    )
            finally:
                engine.dispose()
            print(json.dumps(result, indent=2))
            if not args.no_ui:
                raise SystemExit(launch_dashboard(args.port, url=DEMO_URL, scope=result["scope"]))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        if hasattr(error, "errors"):
            print(
                json.dumps(
                    {"validation": [{"field": e["loc"], "type": e["type"]} for e in error.errors()]}
                ),
                file=sys.stderr,
            )
        parser.exit(
            1,
            (
                f"Local workflow failed ({type(error).__name__}). Check doctor "
                f"output, Docker and ownership; credentials are never printed.\n"
            ),
        )


if __name__ == "__main__":
    main()
