"""Owned, temporary PostgreSQL test workflow; no protected database fallback."""

import json
import os
import subprocess
import sys

URL = "postgresql+psycopg://opsdesk_ci@127.0.0.1:55436/opsdesk_lab_ci"
CONTAINER = "opsdesk-tests-postgres-1"


def inspect_owned():
    result = subprocess.run(["docker", "inspect", CONTAINER], capture_output=True, text=True)
    if result.returncode:
        return False
    info = json.loads(result.stdout)[0]
    if (
        info["Config"].get("Labels", {}).get("opsdesk.owner") != "opsdesk-tests"
        or any(m["Type"] != "tmpfs" for m in info["Mounts"])
        or "/var/lib/postgresql" not in info["HostConfig"].get("Tmpfs", {})
        or info["HostConfig"]["PortBindings"].get("5432/tcp")
        != [{"HostIp": "127.0.0.1", "HostPort": "55436"}]
    ):
        raise ValueError("Refusing an unowned or persistent test instance")
    return True


def run_tests(root, *, unit_only=False, stop=False):
    environment = dict(os.environ)
    for name in ("OPSDESK_DATABASE_URL", "OPSDESK_ALLOW_SANDBOX", "OPSDESK_TEST_OWNED"):
        environment.pop(name, None)
    if not unit_only:
        inspect_owned()
        command = ["docker", "compose", "-f", str(root / "compose.test.yaml")]
        subprocess.run(command + ["config", "--quiet"], check=True)
        if stop:
            if not inspect_owned():
                raise ValueError("No owned test instance exists")
            return subprocess.call(command + ["down"])
        subprocess.run(command + ["up", "-d", "--wait"], check=True)
        if not inspect_owned():
            raise ValueError("Owned test instance did not start")
        environment.update(
            OPSDESK_DATABASE_URL=URL, OPSDESK_ALLOW_SANDBOX="1", OPSDESK_TEST_OWNED="1"
        )
    return subprocess.call(
        [sys.executable, "-m", "pytest"] + (["-m", "not integration"] if unit_only else []),
        env=environment,
    )
