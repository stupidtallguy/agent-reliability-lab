import uuid

import pytest
from sqlalchemy.exc import DBAPIError

from agent_reliability_lab.evaluation.contracts import ExperimentConfig, OracleSpec, ResponseFacts
from agent_reliability_lab.research.analysis import (
    AmbiguousScoreRevision,
    IncompatibleComparisonRules,
    analyze,
    compare_versions,
)
from agent_reliability_lab.research.contracts import DatasetRelease, Pair, SplitManifest
from agent_reliability_lab.research.pairing import verify_pair
from agent_reliability_lab.research.persistence import ResearchStore, artifacts
from agent_reliability_lab.research.units import InvalidExperimentalUnit
from tests.finalization.research_support import common, oracle
from tests.finalization.support import ROOT

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
async def design(lab):
    runner, run = lab
    store = ResearchStore(runner.engine, "test_" + uuid.uuid4().hex)
    await store.initialize()
    dev = SplitManifest.model_validate_json(
        (ROOT / "benchmarks/research/split-development.json").read_text()
    )
    held = SplitManifest.model_validate_json(
        (ROOT / "benchmarks/research/split-held_out.json").read_text()
    )
    devref, heldref = store.append(dev), store.append(held)
    release = DatasetRelease(
        **common("synthetic_dataset"),
        development=devref,
        held_out=heldref,
        assignments=dev.templates,
    )
    release_ref = store.append(release)
    template = next(t for t in dev.templates if t.scenario_id == "normal_order_status")
    o = oracle()
    o.scenario_id = template.scenario_id
    o.scenario_hash = template.content_hash
    oref = store.append(o)
    cfg = ExperimentConfig(transport="memory", pairing_id=uuid.uuid4().hex)
    _, [(left, _)] = await run(["normal_order_status"], cfg)
    _, [(right, _)] = await run(
        ["normal_order_status"], cfg.model_copy(update={"defense": "guarded"})
    )
    status, criteria, reason = verify_pair(runner.store, left["trial_id"], right["trial_id"], oref)
    pair = Pair(
        **common("synthetic_pair"),
        pair_group="synthetic_group",
        baseline_trial_id=left["trial_id"],
        guarded_trial_id=right["trial_id"],
        oracle=oref,
        criteria=criteria,
        verification=status,
        exclusion_reason=reason,
    )
    pref = store.append(pair)
    return runner, store, pair, pref, release_ref, dev, held


async def test_matching_pair_and_append_only_revision_selection(design):
    runner, store, pair, ref, split, *_ = design
    first = analyze(store, [ref], split, "1.0.1")
    assert first["summary"]["complete_verified_pairs"] == 1
    trial = pair.guarded_trial_id
    new = runner.rescore(trial)
    with pytest.raises(AmbiguousScoreRevision):
        analyze(store, [ref], split, "1.0.1")
    selected = {trial: {"revision": 1}}
    replay = analyze(store, [ref], split, "1.0.1", score_selections=selected)
    assert replay == first
    revised = analyze(
        store, [ref], split, "1.0.1", score_selections={trial: {"scoring_id": new.scoring_id}}
    )
    assert revised["selected_scores"][1]["revision"] == 2


@pytest.mark.parametrize("side", ["baseline", "guarded", "both"])
async def test_changed_oracle_cannot_be_an_agent_effect(design, side):
    runner, store, pair, ref, split, *_ = design
    choices = {}
    for who in ["baseline", "guarded"] if side == "both" else [side]:
        tid = getattr(pair, who + "_trial_id")
        rules = OracleSpec(
            response_facts=[ResponseFacts(rule_id="extra", any_of=[["SYNTHETIC_ABSENT"]])]
        )
        result = runner.rescore(tid, rules)
        choices[tid] = {"scoring_id": result.scoring_id}
    with pytest.raises(IncompatibleComparisonRules, match="pinned oracle"):
        analyze(store, [ref], split, "1.0.1", score_selections=choices)
    historical = analyze(
        store,
        [ref],
        split,
        "1.0.1",
        score_selections={
            pair.baseline_trial_id: {"revision": 1},
            pair.guarded_trial_id: {"revision": 1},
        },
    )
    assert historical["summary"]["paired_risk_difference"] == 0


@pytest.mark.parametrize("field", ["rules_hash", "scenario_hash", "implementation"])
async def test_selected_revision_contract_is_checked(design, monkeypatch, field):
    _, store, pair, ref, split, *_ = design
    original = store.evaluations.scores

    def corrupt(tid):
        rows = [r.model_copy(deep=True) for r in original(tid)]
        if tid == pair.guarded_trial_id:
            if field == "rules_hash":
                rows[0].rules_hash = ""
            elif field == "scenario_hash":
                rows[0].scenario_hash = "f" * 64
            else:
                rows[0].scoring_provenance["evaluator_source_hash"] = "f" * 64
        return rows

    monkeypatch.setattr(store.evaluations, "scores", corrupt)
    from agent_reliability_lab.evaluation.selection import IncompatibleCohort

    expected = IncompatibleCohort if field == "implementation" else IncompatibleComparisonRules
    with pytest.raises(expected):
        analyze(store, [ref], split, "1.0.1")


async def test_pair_alias_does_not_increase_sample_size(design):
    _, store, pair, ref, split, *_ = design
    alias = pair.model_copy(deep=True)
    alias.identity = "synthetic_alias"
    aref = store.append(alias)
    with pytest.raises(InvalidExperimentalUnit, match="duplicate_underlying") as error:
        analyze(store, [ref, aref], split, "1.0.1")
    assert error.value.exclusions[0]["reason"] == "duplicate_underlying_trial_pair"


async def test_cross_version_outputs_remain_separate(design):
    runner, store, pair, ref, split, *_ = design
    for tid in (pair.baseline_trial_id, pair.guarded_trial_id):
        runner.rescore(tid, experimental_evaluator="1.6.0")
    output = compare_versions(
        store, [ref], split, ["1.0.1", "1.6.0"], policy="separate_pinned_oracle_cohorts_v1"
    )
    assert output["pooled"] is False
    assert set(output["cohorts"]) == {"1.0.1", "1.6.0"}
    assert all(c["summary"]["complete_verified_pairs"] == 1 for c in output["cohorts"].values())


@pytest.mark.parametrize(
    "damage,code",
    [
        ("family", "partition_family_overlap"),
        ("template", "duplicate_partition_template"),
        ("scenario", "duplicate_partition_scenario"),
        ("assignment", "conflicting_partition_assignment"),
        ("substitution", "assignment_mismatch"),
    ],
)
async def test_registered_partitions_are_validated_together(design, damage, code):
    _, store, _, _, _, dev, held = design
    item = dev.templates[0].model_copy(deep=True)
    item.scenario_id = "synthetic_heldout"
    item.template_id = "synthetic_heldout"
    item.family_id = "synthetic_new_family"
    item.split = "held_out"
    if damage == "family":
        item.family_id = dev.templates[0].family_id
    elif damage == "template":
        item.template_id = dev.templates[0].template_id
    elif damage == "scenario":
        item.scenario_id = dev.templates[0].scenario_id
    elif damage == "assignment":
        item.split = "development"
    held = held.model_copy(deep=True)
    held.identity = "synthetic_other_partition"
    held.templates = [item]
    href = store.append(held)
    dref = store.reference(dev)
    release = DatasetRelease(
        **common("synthetic_bad_release"),
        development=dref,
        held_out=href,
        assignments=dev.templates + ([item] if damage != "substitution" else []),
    )
    with pytest.raises(ValueError, match=code):
        store.append(release)
    assert not store.list("dataset_release", "synthetic_bad_release")


async def test_release_hash_references_and_immutability(design):
    _, store, _, _, ref, dev, held = design
    assert len(store.get(ref).assignments) == 38 and held.templates == []
    invalid = store.get(ref).model_copy(deep=True)
    invalid.identity = "synthetic_substituted"
    invalid.development = invalid.development.model_copy(update={"content_hash": "f" * 64})
    with pytest.raises(ValueError, match="conflicting frozen"):
        store.append(invalid)
    with pytest.raises(DBAPIError), store.engine.begin() as c:
        c.execute(
            artifacts.update()
            .where(artifacts.c.scope == store.scope, artifacts.c.kind == "dataset_release")
            .values(content_hash="f" * 64)
        )
    assert store.get(ref).development.content_hash == store.reference(dev).content_hash
