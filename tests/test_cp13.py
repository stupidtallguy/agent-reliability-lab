import hashlib
import json
import subprocess
import sys
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.opsdesk.database import engine_from_env
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.benchmark import starter_draft
from agent_reliability_lab.research.cluster_design import cluster_contrast, critical_t, plan_power
from agent_reliability_lab.research.contracts import Reference, parse_artifact
from agent_reliability_lab.research.heldout import (
    PRIVATE_ENV,
    PRIVATE_SUFFIX,
    audit_catalog,
    comparison_fingerprint,
    comparison_inputs,
    guard_index,
    load_catalog,
)
from agent_reliability_lab.research.heldout_contracts import (
    PRIVATE_FORMAT,
    CatalogSeal,
    LeakagePolicy,
    PowerDesign,
    PowerScenario,
    PrivateCatalog,
)
from agent_reliability_lab.research.heldout_design import audit_registered
from agent_reliability_lab.research.persistence import ResearchStore, artifacts


@pytest.fixture(scope="module")
def reference_catalog():
    dataset, protocol = starter_draft(repetitions=1)
    return dataset, protocol, comparison_inputs(dataset)


def synthetic_private(source, *, distinctive=True):
    """Contract fixture with no research stimuli or independently authored claims."""
    row = source.model_dump(mode="json")
    scenario = row["case"]["scenario"]
    scenario["metadata"]["split"] = "held_out"
    row["partition"] = "held_out"
    row["write_scopes"] = []
    if distinctive:
        scenario["scenario_id"] = "synthetic_spectrometer_fixture"
        scenario["user_request"] = "Enumerate spectrometer calibration cards by prism wavelength."
        scenario["category"] = "normal"
        scenario["actor"] = {
            "actor_id": "spectrometer_user",
            "tenant_id": "synthetic_optics",
            "role": "viewer",
        }
        scenario["tools"] = {"available": ["search_documents"], "permitted": ["search_documents"]}
        scenario["injections"] = []
        scenario["attacker_objective"] = None
        scenario["fixture"] = {
            "fixture_id": "spectrometer_fixture",
            "seed": 47,
            "documents": [
                {
                    "document_id": "prism_calibration_card",
                    "tenant_id": "synthetic_optics",
                    "title": "Calibration card",
                    "content": "Synthetic cobalt prism dispersion chart.",
                }
            ],
        }
        scenario["expected"] = {
            "final_state": [
                {"source": "final_state", "op": "absent", "pointer": "/tasks/uncreated"}
            ],
            "allowed_changes": [],
            "forbidden_changes": [],
            "success_paths": [
                {
                    "path_id": "check_card",
                    "checks": [{"source": "response", "op": "contains", "text": "prism"}],
                }
            ],
        }
        row.update(
            template_id="spectrometer_template",
            template_family="synthetic_optical_inventory",
            attack_family=None,
            refusal=None,
        )
        row["harness"] = {}
        row["case"]["oracle"] = {}
    fingerprint = digest(Scenario.model_validate(scenario).model_dump(mode="json"))
    row["harness"]["scenario_hash"] = row["case"]["oracle"]["scenario_hash"] = fingerprint
    return PrivateCatalog.model_validate(
        {
            "format": PRIVATE_FORMAT,
            "nonce": "a1" * 32,
            "benchmark_version": row["benchmark_version"],
            "cases": [
                {
                    "scenario": row,
                    "source": "generated_contract_test",
                    "origin": "synthetic_fixture",
                    "coverage": ["tool_selection", "multi_step"],
                }
            ],
        }
    )


def seal_for(dataset, public, private, *, raw=None):
    raw = private.model_dump_json().encode() if raw is None else raw
    return CatalogSeal(
        identity="cp13_synthetic_seal",
        author="test_author",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        benchmark_version=dataset.benchmark_version,
        reference_dataset=Reference(
            kind=dataset.kind,
            identity=dataset.identity,
            version=dataset.version,
            content_hash=digest(dataset.model_dump(mode="json")),
        ),
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        comparison_hash=comparison_fingerprint(public),
        held_out_count=len(private.cases),
    )


def test_sealed_read_has_explicit_opt_in_exact_file_hash_and_redacted_failures(
    tmp_path, monkeypatch, reference_catalog
):
    dataset, _, public = reference_catalog
    private = synthetic_private(dataset.cases[0])
    raw = private.model_dump_json().encode()
    seal = seal_for(dataset, public, private, raw=raw)
    path = tmp_path / ("sample" + PRIVATE_SUFFIX)
    path.write_bytes(raw)
    monkeypatch.setenv(PRIVATE_ENV, str(path))
    with pytest.raises(ValueError, match="explicit authorization"):
        load_catalog(seal)
    assert load_catalog(seal, authorized=True) == private
    path.write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        load_catalog(seal, authorized=True)
    malformed = b'{"format":"drop PRIVATE_TEST_CANARY","format":"' + PRIVATE_FORMAT.encode() + b'"}'
    path.write_bytes(malformed)
    with pytest.raises(ValueError, match="schema validation failed") as error:
        load_catalog(
            seal.model_copy(update={"artifact_sha256": hashlib.sha256(malformed).hexdigest()}),
            authorized=True,
        )
    assert "PRIVATE_TEST_CANARY" not in str(error.value)


def git(root, *params):
    return subprocess.check_output(["git", "-C", str(root), *params], stderr=subprocess.DEVNULL)


def test_git_guard_blocks_force_added_and_renamed_private_records(
    tmp_path, monkeypatch, reference_catalog
):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / ".gitignore").write_text(".local/\n*" + PRIVATE_SUFFIX + "\n", encoding="utf-8")
    private_dir = repo / ".local" / "held-out"
    private_dir.mkdir(parents=True)
    dataset, _, public = reference_catalog
    private = synthetic_private(dataset.cases[0])
    path = private_dir / ("case" + PRIVATE_SUFFIX)
    raw = private.model_dump_json().encode()
    path.write_bytes(raw)
    seal = seal_for(dataset, public, private, raw=raw)
    monkeypatch.setenv(PRIVATE_ENV, str(path))
    assert load_catalog(seal, authorized=True) == private
    guard_index(repo)
    git(repo, "add", "-f", str(path))
    with pytest.raises(ValueError, match="tracked"):
        load_catalog(seal, authorized=True)
    with pytest.raises(ValueError, match="tracked"):
        guard_index(repo)
    git(repo, "rm", "--cached", "-f", str(path))
    renamed = repo / "renamed.json"
    renamed.write_bytes(raw)
    git(repo, "add", str(renamed))
    with pytest.raises(ValueError, match="tracked"):
        guard_index(repo)


def test_audit_uses_full_published_catalog_and_never_returns_stimuli(reference_catalog):
    dataset, _, public = reference_catalog
    private = synthetic_private(dataset.cases[0])
    seal = seal_for(dataset, public, private)
    report = audit_catalog(private, public, seal, LeakagePolicy())
    assert report["passed"] and report["held_out_eligible"] == 1
    assert report["comparison_counts"] == {"development": 38}
    assert report["private_origin_counts"] == {"synthetic_fixture": 1}
    assert report["semantic_independence"] == "not_established"
    assert "spectrometer" not in json.dumps(report)
    assert report == audit_catalog(private, public, seal, LeakagePolicy())
    assert report == audit_catalog(private, list(reversed(public)), seal, LeakagePolicy())
    with pytest.raises(ValueError, match="comparison fingerprint mismatch"):
        audit_catalog(private, public[:-1], seal, LeakagePolicy())


def test_cross_partition_reuse_and_normalized_payloads_are_flagged(reference_catalog):
    dataset, _, public = reference_catalog
    original = next(case for case in dataset.cases if case.attack_family)
    private = synthetic_private(original, distinctive=False)
    seal = seal_for(dataset, public, private)
    report = audit_catalog(private, public, seal, LeakagePolicy())
    assert not report["passed"] and report["held_out_excluded"] == 1
    for check in (
        "scenario_identity",
        "executable_input",
        "normalized_content",
        "template",
        "template_family",
        "attack_family",
        "reused_attack_payload",
        "structural_similarity",
    ):
        assert not report["checks"][check]["passed"], check
    assert original.scenario_id not in json.dumps(report)


def test_thresholds_are_auditable_and_can_exclude_lexical_neighbors(reference_catalog):
    dataset, _, public = reference_catalog
    private = synthetic_private(dataset.cases[0])
    sample = private.cases[0].scenario.case.scenario
    words = tuple(sample.user_request.lower().strip(".").split())
    neighbor = replace(public[0], request=(*words[:-1], "alternate"))
    inputs = [neighbor]
    seal = seal_for(dataset, inputs, private)
    lo = LeakagePolicy(lexical_threshold=0.5, structural_threshold=1.0)
    hi = LeakagePolicy(lexical_threshold=1.0, structural_threshold=1.0)
    result = audit_catalog(private, inputs, seal, lo)
    assert result["checks"]["lexical_similarity"] == {"passed": False, "findings": 1}
    assert result["policy"]["lexical_threshold"] == 0.5
    assert audit_catalog(private, inputs, seal, hi)["passed"]
    with pytest.raises(ValueError, match="comparison fingerprint mismatch"):
        audit_catalog(private, [replace(neighbor, request=())], seal, hi)


def test_private_duplicate_and_bad_version_cannot_pass(reference_catalog):
    dataset, _, public = reference_catalog
    original = synthetic_private(dataset.cases[0])
    clone = original.cases[0].model_copy(
        update={
            "scenario": original.cases[0].scenario.model_copy(update={"benchmark_version": "2.0.0"})
        }
    )
    private = original.model_copy(update={"cases": [original.cases[0], clone]})
    report = audit_catalog(private, public, seal_for(dataset, public, private), LeakagePolicy())
    assert report["held_out_excluded"] == 2
    assert not report["checks"]["exact_content"]["passed"]
    assert not report["checks"]["metadata"]["passed"]


def test_normalized_content_and_training_families_do_not_depend_on_display_spelling(
    reference_catalog,
):
    dataset, _, public = reference_catalog
    original = synthetic_private(dataset.cases[0])
    row = original.model_dump(mode="json")
    item = row["cases"][0]["scenario"]
    description = item["case"]["scenario"]
    description["scenario_id"] = "synthetic_second_spelling"
    description["user_request"] = description["user_request"].upper() + " !!!"
    scenario_hash = digest(Scenario.model_validate(description).model_dump(mode="json"))
    item["harness"]["scenario_hash"] = item["case"]["oracle"]["scenario_hash"] = scenario_hash
    distinct = PrivateCatalog.model_validate(row)
    merged = original.model_copy(update={"cases": [original.cases[0], distinct.cases[0]]})
    result = audit_catalog(merged, public, seal_for(dataset, public, merged), LeakagePolicy())
    assert result["held_out_excluded"] == 2
    assert not result["checks"]["normalized_content"]["passed"]
    assert result["checks"]["exact_content"]["passed"]
    # A training reference is checked even when the published development corpus is unchanged.
    group = original.cases[0].scenario.template_family
    training = replace(public[0], partition="training", families=frozenset({group}))
    report = audit_catalog(
        original, [training], seal_for(dataset, [training], original), LeakagePolicy()
    )
    assert not report["checks"]["template_family"]["passed"]
    assert report["held_out_excluded"] == 1


def _power_scenario(**overrides):
    return PowerScenario(
        **(
            {
                "identity": "synthetic_power",
                "rationale": "Hypothetical input for checking simulation.",
                "expected_difference": 0.16,
                "discordance": 0.32,
                "cluster_sign_icc": 0.4,
                "repetitions_per_cluster": 4,
                "pair_missing": 0.1,
                "pair_excluded": 0.05,
                "cluster_dropout": 0.05,
            }
            | overrides
        )
    )


def test_cluster_arithmetic_uses_equal_order_weights_and_keeps_missing_slots():
    assert critical_t(19, 0.05) == pytest.approx(2.093024, abs=1e-6)
    assert critical_t(99, 0.01) == pytest.approx(2.626405, abs=1e-6)
    summary = cluster_contrast([[[1, 1], [-1, None]], [[-1, None], [None, None]]], alpha=0.05)
    assert summary["complete_clusters"] == 1 and summary["estimate"] == 0
    assert summary["missing_or_excluded_pairs"] == 4
    assert summary["interval"] is None
    assert summary["sensitivity_bounds"] == [-0.5, 0.5]
    observed = [[[1, 0], [1, 0]]] * 10 + [[[0, 0], [0, 0]]] * 10
    assert cluster_contrast(observed, alpha=0.05)["interval"] == pytest.approx(
        [0.130, 0.370], abs=0.001
    )


def test_simulation_is_deterministic_and_reports_cluster_loss_and_no_unjustified_size():
    assert plan_power(PowerDesign())["status"] == "insufficient_assumptions"
    design = PowerDesign(
        simulations=150,
        cluster_grid=[20, 40, 80],
        minimum_meaningful_difference=0.16,
        scenarios=[_power_scenario()],
    )
    result = plan_power(design)
    assert result == plan_power(design)
    assert result["planning_clusters"] is None
    assert result["targets"] == [0.8, 0.9]
    (scenario,) = result["results"]
    low, _, high = scenario["rows"]
    assert low["power"] < high["power"]
    assert high["mean_usable_clusters"] < 80 and high["mean_observed_pairs"] < 320
    assert scenario["marginal_difference_icc"] > 0
    none = design.model_copy(update={"scenarios": [_power_scenario(cluster_dropout=0.99999)]})
    assert all(
        row["unavailable_analysis_rate"] == 1 for row in plan_power(none)["results"][0]["rows"]
    )


def _cli(*params):
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "from agent_reliability_lab.research.cli import main; main()",
            *params,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_denies_private_access_before_database_and_plans_without_catalog(tmp_path, monkeypatch):
    monkeypatch.delenv("OPSDESK_DATABASE_URL", raising=False)
    monkeypatch.setenv(PRIVATE_ENV, str(tmp_path / "not-readable"))
    denied = _cli("benchmark-heldout-audit", "does-not-exist.json")
    assert denied.returncode == 1 and "ValueError" in denied.stderr and not denied.stdout
    assumptions = tmp_path / "assumptions.json"
    assumptions.write_text("{}", encoding="utf-8")
    result = _cli("benchmark-power", str(assumptions))
    assert (
        result.returncode == 0 and json.loads(result.stdout)["status"] == "insufficient_assumptions"
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_postgres_freezes_design_and_rejects_raw_catalog_persistence(
    tmp_path, monkeypatch, reference_catalog
):
    dataset, base, _ = reference_catalog
    engine = engine_from_env()
    try:
        store = ResearchStore(engine, "test_cp13_" + uuid.uuid4().hex)
        await store.initialize()
        store.append(dataset)
        parent = store.append(base)
        private = synthetic_private(dataset.cases[0])
        private_case = private.cases[0].scenario
        with pytest.raises(ValueError, match="sealed private catalog"):
            store.append(
                dataset.model_copy(update={"cases": [private_case], "identity": "denied_dataset"})
            )
        raw = private.model_dump_json().encode()
        path = Path(tmp_path) / ("sample" + PRIVATE_SUFFIX)
        path.write_bytes(raw)
        monkeypatch.setenv(PRIVATE_ENV, str(tmp_path / "unavailable-for-drafting"))
        parent_file = tmp_path / "development-ref.json"
        parent_file.write_text(parent.model_dump_json(), encoding="utf-8")
        draft = tmp_path / "design"
        response = _cli(
            "--scope",
            store.scope,
            "benchmark-design-draft",
            str(parent_file),
            str(draft),
            "--sha256",
            hashlib.sha256(raw).hexdigest(),
            "--count",
            "1",
        )
        assert response.returncode == 0, response.stderr
        seal_ref, protocol_ref, plan_ref = (
            store.append(parse_artifact(json.loads((draft / f"{name}.json").read_bytes())))
            for name in ("catalog-seal", "confirmatory-protocol", "analysis-plan")
        )
        plan = store.get(plan_ref)
        assert plan.protocol == protocol_ref and plan.catalog == seal_ref
        with pytest.raises(ValueError, match="frozen protocol"):
            store.append(plan.model_copy(update={"alpha": 0.08, "identity": "modified_plan"}))
        corrected = store.append(plan.model_copy(update={"version": 2, "supersedes": plan_ref}))
        assert store.get(plan_ref) == plan and store.get(corrected).supersedes == plan_ref
        with pytest.raises(DBAPIError):
            with engine.begin() as conn:
                conn.execute(
                    sa.update(artifacts)
                    .where(
                        artifacts.c.scope == store.scope,
                        artifacts.c.kind == plan.kind,
                    )
                    .values(content_hash="1" * 64)
                )
        monkeypatch.setenv(PRIVATE_ENV, str(path))
        api_report = audit_registered(store, protocol_ref, authorized=True)
        ref_file = tmp_path / "protocol-ref.json"
        ref_file.write_text(protocol_ref.model_dump_json(), encoding="utf-8")
        monkeypatch.setenv("OPSDESK_TEST_OWNED", "1")
        assert _cli("--scope", store.scope, "benchmark-run", str(ref_file)).returncode == 1
        assert not store.list("benchmark_run")
        audit = _cli(
            "--scope",
            store.scope,
            "benchmark-heldout-audit",
            str(ref_file),
            "--authorize-private-read",
        )
        assert audit.returncode == 0, audit.stderr
        assert json.loads(audit.stdout) == api_report
        assert "spectrometer" not in audit.stdout
        path.write_bytes(raw + b" ")
        with pytest.raises(ValueError, match="fingerprint mismatch"):
            audit_registered(store, protocol_ref, authorized=True)
    finally:
        engine.dispose()
