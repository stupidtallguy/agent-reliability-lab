import asyncio
import copy
import json
import sys
from pathlib import Path

import pytest

from agent_reliability_lab.agent.config import AgentConfig
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.agent.provenance_v3 import verify_projection_v3 as verify_projection
from agent_reliability_lab.agent.tool_adapter import ToolSession
from agent_reliability_lab.evaluation.evidence import collect
from tests.finalization.support import ANSWER, DOC, WRITE
from tests.remediation16.support import evaluate as legacy_evaluate

from .support import configuration


def evaluate(trial, evidence):
    return legacy_evaluate(trial, evidence, version="1.7.0")


pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_v170_stdio_process_restart_keeps_original_intent_and_commit(lab):
    runner, run = lab
    config = configuration(transport="stdio")
    config.scripts["attack_hijack"] = copy.deepcopy([DOC, WRITE, ANSWER])
    trial, _ = await run(config=config, execution_options={"pause_before_tools": True})
    execution_id = trial["execution_id"]
    host = AgentExecution(runner.engine)
    cfg = AgentConfig.model_validate_json(json.dumps(host.store.get(execution_id)["config"]))

    async def worker(mode):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).parents[1] / "adversarial/attribution_restart_worker.py"),
            mode,
            execution_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with asyncio.timeout(60):
            out, err = await process.communicate()
        return process.returncode, out, err

    assert (await worker("crash"))[0] == 29
    initial = {
        key: trial["evidence"][key]
        for key in (
            "initial",
            "initial_full",
            "marker",
            "seed_hash",
            "initial_hash",
            "fixture_hash",
            "tool_access",
        )
    }
    async with ToolSession(runner.engine, host.launch(cfg), cfg) as session:
        catalog = session.catalog

    def capture():
        e = collect(
            runner.engine,
            runner.manager.open(trial["sandbox_run_id"]),
            execution_id,
            initial,
            catalog,
            None,
        )
        e.experimental = copy.deepcopy(trial["evidence"]["experimental"])
        e.trial_binding = copy.deepcopy(trial["evidence"]["trial_binding"])
        verify_projection(e)
        return e

    before = evaluate(trial, capture())
    assert before.attacker_success is True, before.model_dump_json()
    code, out, err = await worker("resume")
    assert code == 0, err.decode(errors="replace")
    assert json.loads(out)["status"] == "completed"
    e = capture()
    after = evaluate(trial, e)
    assert after.attacker_success is True, after.model_dump_json()
    assert len(e.receipts) == len(e.audits) == 1
    assert (
        before.experimental["objectives"][0]["attribution"]["matched_proposal_ids"]
        == after.experimental["objectives"][0]["attribution"]["matched_proposal_ids"]
    )
    assert runner.cleanup(trial["trial_id"])["status"] == "cleaned"
