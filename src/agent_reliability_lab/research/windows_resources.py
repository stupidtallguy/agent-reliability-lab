"""Read-only Windows process and memory observations for local qualifications."""

import ctypes
import json
import subprocess
import sys
from datetime import UTC, datetime

SCHEMA = "windows_local_resources_v1"
INFRASTRUCTURE = {
    "docker desktop.exe": "docker",
    "com.docker.backend.exe": "docker",
    "com.docker.build.exe": "docker",
    "vmmem": "wsl",
    "vmmemwsl": "wsl",
    "wslhost.exe": "wsl",
    "wslservice.exe": "wsl",
}
PROCESS_COMMAND = """
$metrics = @{}
Get-Process | ForEach-Object { $metrics[[uint32]$_.Id] = $_ }
$rows = @(Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object {
    $created = if ($_.CreationDate) { $_.CreationDate.ToUniversalTime() }
    $sample = $metrics[[uint32]$_.ProcessId]
    $same = $false
    if ($created -and $sample) {
        try {
            $offset = $sample.StartTime.ToUniversalTime() - $created
            $same = [math]::Abs($offset.TotalMilliseconds) -lt 1
        } catch {}
    }
    @{
        pid = $_.ProcessId
        parent_pid = $_.ParentProcessId
        executable = $_.Name
        path = $_.ExecutablePath
        created_at = $(if ($created) { $created.ToString('o') })
        working_set_bytes = $(if ($same) { $sample.WorkingSet64 })
        private_bytes = $(if ($same) { $sample.PrivateMemorySize64 })
    }
})
ConvertTo-Json -InputObject $rows -Compress
"""


def _command(*args):
    try:
        return subprocess.check_output(args, encoding="utf-8", errors="replace", timeout=8).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def process_inventory():
    raw = _command(
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + PROCESS_COMMAND,
    )
    try:
        inventory = json.loads(raw) if raw is not None else None
    except ValueError:
        return None
    if not isinstance(inventory, list):
        return None
    for process in inventory:
        for name in ("working_set_bytes", "private_bytes"):
            value = process[name]
            if type(value) is not int or value < 0:
                process[name] = None
    return inventory


def system_memory():
    class Performance(ctypes.Structure):
        _fields_ = (
            [("size", ctypes.c_uint32)]
            + [
                (name, ctypes.c_size_t)
                for name in (
                    "commit",
                    "limit",
                    "peak",
                    "ram",
                    "available",
                    "cache",
                    "kernel",
                    "paged",
                    "nonpaged",
                    "page",
                )
            ]
            + [(name, ctypes.c_uint32) for name in ("handles", "processes", "threads")]
        )

    data = Performance()
    data.size = ctypes.sizeof(data)
    if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(data), data.size):
        return dict(available_bytes=None, committed_bytes=None, commit_limit_bytes=None)
    return {
        "available_bytes": data.available * data.page,
        "committed_bytes": data.commit * data.page,
        "commit_limit_bytes": data.limit * data.page,
    }


def gpu_memory():
    raw = _command(
        "nvidia-smi", "--query-gpu=index,memory.used,memory.total", "--format=csv,noheader,nounits"
    )
    if raw is None:
        return None
    result = []
    for line in raw.splitlines():
        fields = line.split(",")
        if len(fields) != 3:
            return None
        index, used, total = (int(s) if (s := part.strip()).isdigit() else None for part in fields)
        result.append({"index": index, "used_mib": used, "total_mib": total})
    return result or None


def identity(process):
    return process["pid"], process["created_at"]


class ProcessTracker:
    """Bind roots and observed descendants to PID plus creation timestamp."""

    def __init__(self):
        self.roots = {}
        self.active = {}

    def bind(self, role, pid, inventory):
        root = next((p for p in inventory or () if p["pid"] == pid and p["created_at"]), None)
        if root is None:
            raise ValueError(f"{role} process identity unavailable")
        self.roots[identity(root)] = role
        return identity(root)

    def observe(self, inventory):
        if inventory is None:
            return None
        by_pid = {process["pid"]: process for process in inventory}
        selected = {}
        roles = {k: v["role"] for k, v in self.active.items()} | self.roots

        def role_for(process):
            current = process
            while current["created_at"]:
                role = roles.get(identity(current)) or INFRASTRUCTURE.get(
                    current["executable"].lower()
                )
                if role:
                    if current is process:
                        return role
                    if role == "block_launcher" and process["executable"].lower() in {
                        "python.exe",
                        "pythonw.exe",
                    }:
                        return "block_worker"
                    if role == "ollama_listener" and process["executable"].lower() == (
                        "llama-server.exe"
                    ):
                        return "ollama_runner"
                    if role in {"postgres", "docker", "wsl"}:
                        return role
                    return f"{role}_child"
                parent = by_pid.get(current["parent_pid"])
                if (
                    parent is None
                    or parent is current
                    or not parent["created_at"]
                    or datetime.fromisoformat(parent["created_at"])
                    >= datetime.fromisoformat(current["created_at"])
                ):
                    break
                current = parent
            return None

        for process in inventory:
            if role := role_for(process):
                selected[identity(process)] = process | {"status": "observed", "role": role}
        departed = [
            v | {"status": "departed", "working_set_bytes": None, "private_bytes": None}
            for k, v in self.active.items()
            if k not in selected
            and (k[0] not in by_pid or (by_pid[k[0]]["created_at"] and identity(by_pid[k[0]]) != k))
        ]
        uncertain = {
            k: v
            for k, v in self.active.items()
            if k[0] in by_pid and not by_pid[k[0]]["created_at"]
        }
        self.active = selected | uncertain
        return (
            list(selected.values())
            + departed
            + [
                v | {"status": "unknown", "working_set_bytes": None, "private_bytes": None}
                for v in uncertain.values()
            ]
        )


def sample(tracker, phase):
    if sys.platform != "win32":
        raise OSError("local resource observation requires Windows")
    moment = datetime.now(UTC).isoformat()
    memory = system_memory()
    processes = tracker.observe(process_inventory())
    return {
        "schema": SCHEMA,
        "timestamp": moment,
        "phase": phase,
        "system": memory,
        "processes": processes,
        "gpu_devices": gpu_memory(),
        "finished_at": datetime.now(UTC).isoformat(),
    }
