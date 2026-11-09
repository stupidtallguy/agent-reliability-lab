import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from agent_reliability_lab.agent import tables as a
from agent_reliability_lab.agent.persistence import ExecutionStore
from agent_reliability_lab.agent.provenance import verify_projection
from agent_reliability_lab.agent.state import Decision

from .support import evaluate, frozen

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_requests_and_journal_are_immutable(lab):
    runner, run = lab
    _, [(trial, result)] = await run(["attack_body_answer"])
    assert result.attacker_success is True
    e = frozen(trial)
    verify_projection(e)
    store = ExecutionStore(runner.engine)
    request = e.requests[0]
    with pytest.raises(ValueError, match="completion conflict"):
        store.model_finished(
            e.execution_id, request["request_id"], Decision(answer="changed"), 1, 1
        )
    with pytest.raises(ValueError, match="completion conflict"):
        store.model_finished("0" * 32, request["request_id"], Decision(answer="changed"), 1, 1)
    statements = [
        a.requests.update()
        .where(a.requests.c.request_id == request["request_id"])
        .values(reply={}),
        a.events.delete().where(a.events.c.execution_id == e.execution_id),
        a.provenance.delete().where(a.provenance.c.execution_id == e.execution_id),
    ]
    for statement in statements:
        with pytest.raises(DBAPIError, match="immutable"):
            with runner.engine.begin() as connection:
                connection.execute(statement)
    from agent_reliability_lab.evaluation import tables as evaluation_tables

    with pytest.raises(DBAPIError, match="frozen trial"):
        with runner.engine.begin() as connection:
            connection.execute(
                evaluation_tables.trials.update()
                .where(evaluation_tables.trials.c.trial_id == trial["trial_id"])
                .values(evidence={})
            )
    verify_projection(e)
    assert store.provenance(e.execution_id) == e.provenance


async def test_sealed_decision_tampering_does_not_score(lab):
    _, run = lab
    _, [(trial, result)] = await run(["attack_body_answer"])
    assert result.attacker_success is True
    evidence = frozen(trial)
    evidence.requests[-1]["answer_hash"] = "f" * 64
    changed = evaluate(trial, evidence)
    assert changed.attacker_success is None
    assert changed.findings


async def test_new_execution_has_bounded_original_proposals(lab):
    runner, run = lab
    _, [(trial, _)] = await run(["attack_hijack"])
    e = frozen(trial)
    verify_projection(e)
    originals = [r for r in e.provenance if r["kind"] == "original_proposal"]
    assert len(originals) == len(e.operations)
    assert all(r["body"]["original"]["arguments_json"] for r in originals)
    with runner.engine.connect() as connection:
        assert connection.execute(
            sa.select(sa.func.count())
            .select_from(a.provenance)
            .where(a.provenance.c.execution_id == e.execution_id)
        ).scalar_one() == len(e.provenance)
