import json
from types import SimpleNamespace

import pytest

from agent_reliability_lab.platform import cli, testing


@pytest.mark.parametrize("target", ["demo", "tests"])
@pytest.mark.parametrize("damage", [None, "bind", "volume", "missing_tmpfs", "owner", "port"])
def test_only_owned_loopback_tmpfs_resources_are_accepted(monkeypatch, target, damage):
    name = "opsdesk-" + target
    port = "55435" if target == "demo" else "55436"
    info = dict(
        Config={"Labels": {"opsdesk.owner": name}},
        Mounts=[{"Type": "tmpfs"}],
        HostConfig={
            "Tmpfs": {"/var/lib/postgresql": "size=1g"},
            "PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]},
        },
    )
    if damage in {"bind", "volume"}:
        info["Mounts"][0]["Type"] = damage
    elif damage == "missing_tmpfs":
        info["HostConfig"]["Tmpfs"] = {}
    elif damage == "owner":
        info["Config"]["Labels"] = {}
    elif damage == "port":
        info["HostConfig"]["PortBindings"]["5432/tcp"][0]["HostIp"] = "0.0.0.0"
    module = cli if target == "demo" else testing
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps([info])),
    )
    check = cli.inspect_demo if target == "demo" else testing.inspect_owned
    if damage:
        with pytest.raises((RuntimeError, ValueError), match="Refusing"):
            check()
    else:
        assert check()
