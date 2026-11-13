"""Owned, temporary PostgreSQL test workflow; no protected database fallback."""

import os
import subprocess
import sys

from agent_reliability_lab.platform.containers import compose
from agent_reliability_lab.platform.containers import inspect_owned as inspect_container
from agent_reliability_lab.platform.demo import assets

URL = "postgresql+psycopg://opsdesk_ci@127.0.0.1:55436/opsdesk_lab_ci"


def inspect_owned():
    return inspect_container("opsdesk-tests", "55436") is not None


def run_tests(root, *, unit_only=False, stop=False):
    if not stop and not (root / "tests").is_dir():
        raise ValueError("Run tests from a source checkout or supply --workspace")
    environment = dict(os.environ)
    for name in ("OPSDESK_DATABASE_URL", "OPSDESK_ALLOW_SANDBOX", "OPSDESK_TEST_OWNED"):
        environment.pop(name, None)
    if not unit_only:
        inspect_owned()
        command = compose(assets(), "opsdesk-tests", "compose.test.yaml")
        subprocess.run(command + ["config", "--quiet"], check=True)
        if stop:
            if not inspect_owned():
                raise ValueError("No owned test instance exists")
            return subprocess.call(command + ["down", "postgres"])
        subprocess.run(command + ["up", "-d", "--wait", "postgres"], check=True)
        if not inspect_owned():
            raise ValueError("Owned test instance did not start")
        environment.update(
            OPSDESK_DATABASE_URL=URL, OPSDESK_ALLOW_SANDBOX="1", OPSDESK_TEST_OWNED="1"
        )
    return subprocess.call(
        [sys.executable, "-m", "pytest"] + (["-m", "not integration"] if unit_only else []),
        env=environment,
        cwd=root,
    )
