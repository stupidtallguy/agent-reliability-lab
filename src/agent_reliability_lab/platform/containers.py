"""Compose commands scoped to the bundled disposable projects."""

import json
import subprocess


def compose(root, project, filename):
    # An inherited COMPOSE_PROJECT_NAME overrides the name declared in YAML.
    return ["docker", "compose", "--project-name", project, "-f", str(root / filename)]


def inspect_owned(project, port):
    container = project + "-postgres-1"
    result = subprocess.run(
        ["docker", "container", "inspect", container], capture_output=True, text=True
    )
    if result.returncode:
        if f"No such container: {container}" in result.stderr:
            return None
        raise RuntimeError("Unable to inspect the disposable PostgreSQL container")
    info = json.loads(result.stdout)[0]
    config = info["HostConfig"]
    labels = info["Config"].get("Labels") or {}
    if (
        labels.get("opsdesk.owner") != project
        or labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.service") != "postgres"
        or any(m["Type"] != "tmpfs" for m in info["Mounts"])
        or "/var/lib/postgresql" not in (config.get("Tmpfs") or {})
        or (config.get("PortBindings") or {}).get("5432/tcp")
        != [{"HostIp": "127.0.0.1", "HostPort": port}]
    ):
        raise ValueError("Refusing an unowned, persistent or differently bound PostgreSQL instance")
    return info
