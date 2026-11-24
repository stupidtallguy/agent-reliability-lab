import json

from agent_reliability_lab.research import windows_resources
from agent_reliability_lab.research.windows_resources import ProcessTracker


def process(pid, parent, sec, executable="python.exe"):
    return {
        "pid": pid,
        "parent_pid": parent,
        "created_at": None if sec is None else f"2026-11-24T01:00:{sec:02d}+00:00",
        "executable": executable,
        "path": None,
        "working_set_bytes": 100,
        "private_bytes": 200,
    }


def test_descendant_identity_survives_parent_exit_but_not_pid_reuse():
    tracker = ProcessTracker()
    launcher, worker = process(1, 0, 1), process(2, 1, 2)
    listener, runner = process(3, 0, 1, "ollama.exe"), process(4, 3, 3, "llama-server.exe")
    tracker.bind("block_launcher", 1, [launcher])
    tracker.bind("ollama_listener", 3, [listener])
    observed = tracker.observe([launcher, worker, listener, runner])
    assert {p["pid"]: p["role"] for p in observed} == {
        1: "block_launcher",
        2: "block_worker",
        3: "ollama_listener",
        4: "ollama_runner",
    }
    assert tracker.observe(None) is None
    new_parent = process(1, 0, 5)
    unrelated = process(5, 1, 6)
    observed = tracker.observe([new_parent, unrelated, worker, listener, runner])
    assert {p["pid"]: p["status"] for p in observed} == {
        1: "departed",
        2: "observed",
        3: "observed",
        4: "observed",
    }
    assert observed[-1]["working_set_bytes"] is None


def test_inaccessible_creation_is_unknown_then_original_identity_departs():
    tracker = ProcessTracker()
    postgres = process(6, 0, 1, "postgres.exe")
    tracker.bind("postgres", 6, [postgres])
    tracker.observe([postgres])
    (unknown,) = tracker.observe([process(6, 0, None, "postgres.exe")])
    assert (unknown["status"], unknown["private_bytes"]) == ("unknown", None)
    (departed,) = tracker.observe([process(6, 0, 4)])
    assert departed["status"] == "departed"
    assert tracker.observe([process(6, 0, 4)]) == []


def test_inaccessible_windows_metrics_normalize_to_unknown(monkeypatch):
    raw = json.dumps(
        [process(6, 0, 1, "wslservice.exe") | {"working_set_bytes": {}, "private_bytes": 0}]
    )
    monkeypatch.setattr(windows_resources, "_command", lambda *args: raw)
    (row,) = windows_resources.process_inventory()
    assert row["working_set_bytes"] is None
    assert row["private_bytes"] == 0
