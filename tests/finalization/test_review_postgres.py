import json
import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.research.contracts import Adjudication
from agent_reliability_lab.research.persistence import ResearchStore, artifacts

from .research_support import attestation, common, oracle, reviewer

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def research():
    engine = engine_from_env()
    store = ResearchStore(engine, "test_" + uuid.uuid4().hex)
    await store.initialize()
    yield store
    engine.dispose()


async def test_oracle_review_remains_pending_without_real_humans(research):
    store = research
    ref = store.append(oracle())
    assert store.review_status(ref)["status"] == "pending_independent_human_review"
    for name in ("synthetic_first", "synthetic_second"):
        who = reviewer(name)
        store.append(who)
        store.append(attestation(store, ref, who))
    status = store.review_status(ref)
    assert status["review_count"] == 2 and status["human_review_count"] == 0
    assert status["status"] == "pending_independent_human_review"
    assert not status["independent_identity_verification"]


async def test_append_only_review_versions_and_disagreement(research):
    store = research
    ref = store.append(oracle())
    first, second = reviewer("synthetic_first"), reviewer("synthetic_second")
    for who in (first, second):
        store.append(who)
    a = attestation(store, ref, first)
    store.append(a)
    b = attestation(store, ref, second, "changes_required")
    store.append(b)
    assert store.review_status(ref)["status"] == "unresolved_disagreement"
    with pytest.raises(ValueError, match="append consecutively"):
        store.append(a)
    with pytest.raises(DBAPIError, match="frozen"):
        with store.engine.begin() as connection:
            connection.execute(artifacts.delete().where(artifacts.c.scope == store.scope))
    store.append(attestation(store, ref, second, version=2))
    assert len(store.list("attestation")) == 3
    assert store.get(store.reference(b)).decision == "changes_required"
    alias = attestation(store, ref, second)
    alias.identity = "synthetic_stale_alias"
    with pytest.raises(ValueError, match="one attestation stream"):
        store.append(alias)
    assert len(store.list("attestation")) == 3


async def test_adjudicator_must_be_independent(research):
    store = research
    ref = store.append(oracle())
    reviews = []
    for name in ("synthetic_first", "synthetic_second"):
        who = reviewer(name, "both")
        store.append(who)
        reviews.append(store.append(attestation(store, ref, who, "changes_required")))
    bad = Adjudication(
        **common("resolution", "synthetic_first"),
        oracle=ref,
        adjudicator=store.reference(reviewer("synthetic_first", "both")),
        attestations=reviews,
        decision="approve",
        rationale="Synthetic test.",
        evidence_references=["test"],
        origin="synthetic_test",
    )
    # References include timestamps and are hash-pinned, so use the persisted reviewer.
    row = store.list("reviewer", "synthetic_first")[0]
    bad.adjudicator = store.reference(type(who).model_validate_json(json.dumps(row["body"])))
    with pytest.raises(ValueError, match="independent adjudicator"):
        store.append(bad)
    third = reviewer("synthetic_third", "adjudicator")
    store.append(third)
    bad.author, bad.adjudicator = third.identity, store.reference(third)
    store.append(bad)
    assert store.review_status(ref)["status"] == "unresolved_disagreement"


async def test_human_origin_requires_personal_opt_in(research):
    store = research
    ref = store.append(oracle())
    who = reviewer("synthetic_first")
    store.append(who)
    a = attestation(store, ref, who)
    a.origin = "human_declared"
    with pytest.raises(ValueError, match="real human"):
        store.append(a)
    # Never persist fabricated human attestations, even in tests.
    assert not store.list("attestation")
