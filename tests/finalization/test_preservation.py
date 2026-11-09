import json

from agent_reliability_lab.evaluation.preservation import compare, verify_sources

from .support import ROOT


def test_every_historical_scorer_matches_its_canonical_frozen_source():
    values = json.loads((ROOT / "benchmarks/research/historical-scorers.json").read_text())
    assert len(values) == 5 and all(verify_sources(ROOT, values).values())


def test_new_records_are_allowed_but_prior_modification_or_removal_is_detected():
    before = {"test.records": {"primary": ["id"], "rows": {"[1]": "old"}}}
    assert compare(
        before, {"test.records": {"primary": ["id"], "rows": {"[1]": "old", "[2]": "new"}}}
    )["verified"]
    assert not compare(before, {"test.records": {"primary": ["id"], "rows": {"[1]": "modified"}}})[
        "verified"
    ]
    assert not compare(before, {})["verified"]


def test_only_explicit_alembic_metadata_transitions_are_allowed():
    before = {
        "opsdesk_agent.alembic_version": {
            "primary": ["version_num"],
            "rows": {'["0001_agent"]': "old"},
        }
    }
    current = {
        "opsdesk_agent.alembic_version": {
            "primary": ["version_num"],
            "rows": {'["0002_provenance"]': "new"},
        }
    }
    assert not compare(before, current)["verified"]
    result = compare(
        before, current, migration_heads={"opsdesk_agent.alembic_version": "0002_provenance"}
    )
    assert result["verified"] and len(result["migrations"]) == 1
