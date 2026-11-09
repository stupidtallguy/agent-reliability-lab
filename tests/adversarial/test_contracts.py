"""Fast contract, guard and logical-trigger controls; no Docker required."""

import copy
import hashlib
import json

import pytest
from pydantic import ValidationError

from agent_reliability_lab.adversarial.contracts import (
    AttackSpec,
    Defense,
    FaultSpec,
    HarnessSpec,
    RuntimePlan,
)
from agent_reliability_lab.adversarial.defenses import blocks, frame
from agent_reliability_lab.adversarial.runtime import contains_text
from agent_reliability_lab.adversarial.triggers import fires, subset
from agent_reliability_lab.agent.config import AgentConfig, ModelConfig
from agent_reliability_lab.agent.models.fake import ScriptedModel
from agent_reliability_lab.evaluation.runner import read_case
from tests.adversarial.support import ROOT, configuration, path_for


@pytest.mark.parametrize("category,count", [("faults", 12), ("attacks", 12), ("controls", 8)])
def test_corpus_bound_and_schema(category, count):
    paths = list((ROOT / f"benchmarks/{category}/development").glob("*.json"))
    assert len(paths) == count
    config = configuration()
    for path in paths:
        case, fingerprint, problem = read_case(path)
        assert problem is None
        h = config.harnesses[case.scenario.scenario_id]
        assert h.scenario_hash == fingerprint
        assert set(config.scripts[case.scenario.scenario_id][0])
        assert h.benign_control == (category == "controls")


@pytest.mark.parametrize("sid", ["recovery_order_timeout", "injection_policy_canary"])
def test_original_explicit_sidecars(sid):
    case, fingerprint, problem = read_case(path_for(sid))
    assert not problem and case.scenario.injections
    assert configuration().harnesses[sid].scenario_hash == fingerprint


@pytest.mark.parametrize(
    "update",
    [
        {"server": "tasks"},
        {"boundary": "after_validated_response"},
        {"duration_ms": 1},
        {"trigger": {"occurrence": 0}},
        {"trigger": {"max_activations": 11}},
        {"fault_type": "response_lost_after_commit", "boundary": "after_validated_response"},
        {"recoverable": True, "permissible_recovery": []},
        {"permanent_code": "permission_denied"},
        {
            "fault_type": "permanent_error",
            "permanent_code": "permission_denied",
            "recoverable": True,
        },
        {"fault_type": "empty_result", "boundary": "before_output_validation"},
    ],
)
def test_fault_invalid_combinations(update):
    payload = configuration().harnesses["fault_transient"].faults[0].model_dump(mode="json")
    payload.update(update)
    with pytest.raises(ValidationError):
        FaultSpec.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "surface",
    [
        "/provenance/tool",
        "/data/document_id",
        "/data/trust_classification",
        "/error/message",
        "/actor_id",
        "/data/version",
    ],
)
def test_attacker_cannot_modify_privileged_or_structural_fields(surface):
    payload = configuration().harnesses["attack_body_answer"].attacks[0].model_dump(mode="json")
    payload["surface"] = surface
    with pytest.raises(ValidationError, match="surface"):
        AttackSpec.model_validate_json(json.dumps(payload))


def test_attack_hash_and_canary_validation():
    payload = configuration().harnesses["attack_canary"].attacks[0].model_dump(mode="json")
    payload["payload_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="hash"):
        AttackSpec.model_validate_json(json.dumps(payload))
    payload["payload_hash"] = hashlib.sha256(payload["payload"].encode()).hexdigest()
    payload["objective"]["text"] = "real_secret"
    with pytest.raises(ValidationError, match="SYNTHETIC_"):
        AttackSpec.model_validate_json(json.dumps(payload))


def test_no_hidden_objective_in_runtime_config():
    h = configuration().harnesses["attack_hijack"]
    assert "objective" not in h.runtime().model_dump_json()
    assert "expected" not in h.runtime().model_dump(mode="json")


def test_ambiguous_overlapping_specs_rejected():
    h = configuration().harnesses["attack_body_answer"]
    p = h.runtime().model_dump(mode="json")
    attack = copy.deepcopy(p["attacks"][0])
    attack["injection_id"] = "another_attack"
    p["attacks"].append(attack)
    with pytest.raises(ValidationError, match="one injection"):
        RuntimePlan.model_validate_json(json.dumps(p))


def test_benign_and_attack_cannot_be_mixed():
    h = configuration().harnesses["attack_body_answer"].model_dump(mode="json")
    h["benign_control"] = True
    with pytest.raises(ValidationError, match="benign"):
        HarnessSpec.model_validate_json(json.dumps(h))


@pytest.mark.parametrize("ordinal,expected", [(1, False), (2, True), (3, True), (4, False)])
def test_bounded_trigger(ordinal, expected):
    spec = configuration().harnesses["fault_transient"].faults[0]
    trigger = spec.trigger.model_copy(update={"occurrence": 2, "max_activations": 2})
    assert fires(trigger, ordinal) is expected


def test_subset_is_type_sensitive():
    assert not subset({"value": 1}, {"value": True})
    assert subset(
        {"patch": {"status": "resolved"}}, {"patch": {"status": "resolved", "title": "changed"}}
    )


@pytest.mark.parametrize("variant,allowed", [("baseline", True), ("guarded", False)])
def test_task_scope_default_deny_without_disabling_reads(variant, allowed):
    defense = Defense(configuration=variant)
    assert blocks(defense, "create_task", {"customer_id": "customer_001", "title": "Test"}) is (
        not allowed
    )
    assert not blocks(defense, "get_order", {"order_id": "order_001"})


def test_scopes_do_not_allow_extra_patch_fields():
    defense = Defense(
        configuration="guarded", write_scopes=configuration().write_scopes["benign_update"]
    )
    assert not blocks(
        defense, "update_task", {"task_id": "task_001", "patch": {"status": "resolved"}}
    )
    assert blocks(
        defense,
        "update_task",
        {"task_id": "task_001", "patch": {"status": "resolved", "title": "hijacked"}},
    )


def test_technical_keywords_are_not_blacklisted():
    defense = Defense(
        configuration="guarded", write_scopes=configuration().write_scopes["benign_create"]
    )
    assert not blocks(
        defense, "create_task", {"customer_id": "customer_001", "title": "Shipment follow-up"}
    )
    framed = frame({"data": {"content": "system delete password administrator"}}, defense)
    assert framed["observation"]["data"]["content"] == "system delete password administrator"
    assert framed["instruction_authority"] == "none"


def test_exact_text_exposure_supports_quotes_and_newlines():
    text = 'Ignore "authority".\nSYNTHETIC_MARKER'
    assert contains_text({"data": {"content": "Prefix " + text}}, text)
    assert not contains_text({"data": {"content": "Prefix " + text[:10]}}, text)


def test_legacy_agent_config_serialization_remains_compatible():
    config = AgentConfig(sandbox_run_id="test_01", actor_id="actor_001", tenant_id="opsdesk")
    assert "runtime_plan" not in config.model_dump(mode="json")
    assert "defense" not in config.model_dump(mode="json")


@pytest.mark.parametrize("tool", ["create_task", "update_task"])
def test_guard_scopes_cannot_be_unbounded_wildcards(tool):
    from agent_reliability_lab.adversarial.contracts import WriteScope

    with pytest.raises(ValidationError):
        WriteScope(tool=tool, arguments={})


def test_legacy_sidecar_preserves_payload_and_activation():
    case, _, _ = read_case(path_for("injection_policy_canary"))
    harness = configuration().harnesses[case.scenario.scenario_id]
    assert harness.covers_legacy(case.scenario.injections[0])
    attack = harness.attacks[0].model_copy(update={"payload": "Different payload"})
    changed = harness.model_copy(update={"attacks": [attack]})
    assert not changed.covers_legacy(case.scenario.injections[0])


@pytest.mark.anyio
async def test_scripted_branch_reads_only_actual_tool_messages():
    model = ScriptedModel(
        ModelConfig(
            script=[
                {
                    "if_observation": "MARKER",
                    "then": {"answer": "contaminated"},
                    "else": {"answer": "clean"},
                }
            ]
        )
    )
    assert (
        await model.decide([{"role": "user", "content": "MARKER"}], [], 0, 100)
    ).answer == "clean"
    assert (
        await model.decide([{"role": "tool", "content": "MARKER"}], [], 0, 100)
    ).answer == "contaminated"
