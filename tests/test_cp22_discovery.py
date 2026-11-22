import copy
import json
import subprocess

import pytest
from jsonschema import Draft202012Validator

from agent_reliability_lab.evaluation.source import committed_source
from agent_reliability_lab.mcp.contracts import UpdateTaskInput
from agent_reliability_lab.research.ollama_model import TAG, parse_reply, payload
from agent_reliability_lab.research.pilot_contracts import OllamaProfile


def test_native_schema_roundtrip_preserves_patch_type():
    schema = UpdateTaskInput.model_json_schema()
    tool = {"type": "function", "function": {"name": "update_task", "parameters": schema}}
    profile = OllamaProfile(
        model_digest="a" * 64, template_hash="b" * 64, quantization="Q4_K_M", hardware={}
    )
    wire = json.loads(json.dumps(payload(profile, [], [tool])))
    original = wire["tools"][0]["function"]["parameters"]
    assert original == schema
    assert original["properties"]["patch"] == {"$ref": "#/$defs/TaskPatch"}
    # Offline-only interface probe. The paired study keeps the original nested schema.
    inline = copy.deepcopy(original)
    inline["properties"]["patch"] = inline.pop("$defs")["TaskPatch"]
    examples = [
        ({"status": "resolved"}, True),
        ('{"status":"resolved"}', False),
        ({"title": "New title", "extra": 1}, False),
        ([], False),
        ({"status": "other"}, False),
        ({"title": "x" * 201}, False),
    ]
    for patch, expected in examples:
        args = {"task_id": "task_001", "expected_version": 1, "patch": patch}
        response = dict(
            model=TAG,
            done=True,
            done_reason="stop",
            message=dict(
                role="assistant",
                content="",
                tool_calls=[{"function": {"name": "update_task", "arguments": args}}],
            ),
        )
        (call,) = parse_reply(response, "request").calls
        adapted = json.loads(call.arguments_json)
        assert adapted == args
        assert Draft202012Validator(original).is_valid(adapted) is expected
        assert Draft202012Validator(inline).is_valid(adapted) is expected


def test_committed_source_is_eol_invariant_and_rejects_code_lock_or_inventory_changes(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args]).strip()

    git("init", "-q")
    git("config", "core.autocrlf", "false")
    source = tmp_path / "src"
    source.mkdir()
    package = source / "main.py"
    lock = tmp_path / "uv.lock"
    package.write_bytes(b"RESULT = 1\n")
    lock.write_bytes(b"version = 1\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "fixture",
    )
    head = git("rev-parse", "HEAD").decode()
    frozen = committed_source(source, head)
    package.write_bytes(b"RESULT = 1\r\n")
    assert committed_source(source, head) == frozen
    package.write_bytes(b"RESULT = 2\n")
    with pytest.raises(ValueError, match="main.py"):
        committed_source(source, head)
    package.write_bytes(b"RESULT = 1\n")
    lock.write_bytes(b"version = 2\n")
    with pytest.raises(ValueError, match="uv.lock"):
        committed_source(source, head)
    lock.write_bytes(b"version = 1\n")
    (source / "extra.py").write_bytes(b"RESULT = 5\n")
    with pytest.raises(ValueError, match="inventory"):
        committed_source(source, head)
    with pytest.raises(ValueError, match="checked-out Git commit"):
        committed_source(source, "0" * 40)
