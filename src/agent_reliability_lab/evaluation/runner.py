"""Serial, isolated scenario trials with trusted configuration and independent scoring."""

import hashlib
import json
import platform
import subprocess
import time
import uuid
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.engine import Engine

from agent_reliability_lab.adversarial import HARNESS_VERSION
from agent_reliability_lab.adversarial.contracts import Defense
from agent_reliability_lab.agent.config import AgentConfig
from agent_reliability_lab.agent.execution import AgentExecution
from agent_reliability_lab.agent.state import TERMINAL
from agent_reliability_lab.agent.tool_adapter import ToolSession
from agent_reliability_lab.benchmarks.scenario import Scenario
from agent_reliability_lab.evaluation import EVALUATOR_VERSION
from agent_reliability_lab.evaluation.contracts import Case, Evidence, ExperimentConfig, OracleSpec
from agent_reliability_lab.evaluation.demo import development_script
from agent_reliability_lab.evaluation.evidence import capture_initial, collect
from agent_reliability_lab.evaluation.persistence import EvaluationStore, now
from agent_reliability_lab.evaluation.scoring import excluded, score
from agent_reliability_lab.opsdesk.database import SandboxManager
from agent_reliability_lab.opsdesk.fixtures import digest, from_scenario


def provenance(config: ExperimentConfig) -> dict:
    def git(*args):
        try:
            result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
        except OSError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    commit = config.source_commit or git("rev-parse", "HEAD")
    if commit is None:
        raise ValueError("source_commit is required outside a Git checkout")
    source = Path(__file__).parents[1]
    code_hash = digest(
        {
            path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source.rglob("*.py"))
        }
    )
    lock = Path("uv.lock")
    if config.experimental_evaluator == "1.7.0" and not lock.is_file():
        lock = source / "resources/uv.lock"
    status = git("status", "--porcelain")
    return {
        "source_commit": commit,
        "working_tree_dirty": bool(status) if status is not None else None,
        "source_hash": code_hash,
        "lock_hash": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        "python": platform.python_version(),
        "platform": platform.system(),
        "sdk_versions": {name: version(name) for name in ("langgraph", "mcp", "openai", "psycopg")},
        "evaluator_version": config.experimental_evaluator
        if config.harnesses
        else EVALUATOR_VERSION,
        "harness_version": HARNESS_VERSION if config.harnesses else None,
        "parallelism": 1,
        "model_parameters": {
            "max_output_tokens": config.budgets.max_output_tokens,
            "temperature": "provider_default_not_assumed_deterministic",
        },
    }


def read_case(path: Path) -> tuple[Case | None, str, str | None]:
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        return None, hashlib.sha256(raw).hexdigest(), "scenario_file_too_large"
    try:
        value = json.loads(raw)
        case = (
            Case.model_validate_json(raw)
            if "scenario" in value
            else Case(scenario=Scenario.model_validate_json(raw))
        )
        return case, digest(case.scenario.model_dump(mode="json")), None
    except (ValidationError, ValueError, TypeError):
        return None, hashlib.sha256(raw).hexdigest(), "invalid_scenario_specification"


def trial_agent_config(scenario, config, run_id, source_commit, script):
    """Derive effective host budgets and runtime settings once per planned trial."""
    budgets = config.budgets.model_copy(
        update={
            "max_llm_calls": min(config.budgets.max_llm_calls, scenario.budget.max_model_calls),
            "max_tool_calls": min(config.budgets.max_tool_calls, scenario.budget.max_tool_calls),
            "max_wall_seconds": min(
                config.budgets.max_wall_seconds, float(scenario.budget.max_wall_seconds)
            ),
            "max_output_tokens": min(
                config.budgets.max_output_tokens, scenario.budget.max_total_tokens
            ),
        }
    )
    model_config = config.model.model_copy(update={"script": script or []})
    return AgentConfig(
        source_commit=source_commit,
        sandbox_run_id=run_id,
        actor_id=scenario.actor.actor_id,
        tenant_id=scenario.actor.tenant_id,
        model=model_config,
        budgets=budgets,
        transport=config.transport,
        runtime_plan=config.harnesses[scenario.scenario_id].runtime()
        if scenario.scenario_id in config.harnesses
        else None,
        defense=Defense(
            configuration=config.defense,
            write_scopes=config.write_scopes.get(scenario.scenario_id, []),
        )
        if scenario.scenario_id in config.harnesses or config.defense == "guarded"
        else None,
    )


class ScenarioRunner:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.store = EvaluationStore(engine)
        self.manager = SandboxManager(engine)

    async def run(
        self,
        paths: list[Path],
        config: ExperimentConfig,
        *,
        live=False,
        model_factory=None,
        execution_options: dict | None = None,
        demonstration: bool = False,
        benchmark_context: dict | None = None,
        benchmark_model=None,
    ) -> str:
        if not paths:
            raise ValueError("at least one scenario path is required")
        if benchmark_context is not None and (live or config.model.provider != "fake"):
            raise ValueError("live model execution is disabled in benchmark mode")
        if benchmark_context is not None and model_factory is not None:
            raise ValueError("arbitrary model factories are disabled in benchmark mode")
        if benchmark_model is not None:
            from agent_reliability_lab.research.pilot_model import OfflinePilotModel

            if benchmark_context is None or type(benchmark_model) is not OfflinePilotModel:
                raise ValueError("benchmark model must be the brokered offline adapter")

            def offline_factory(_):
                return benchmark_model

            model_factory = offline_factory
        if demonstration and (config.model.provider != "fake" or config.study is not None):
            raise ValueError("a demonstration must use scripted infrastructure validation")
        if config.model.provider == "openai" and (
            not live or config.model.model_id == "scripted-v1"
        ):
            raise ValueError("live evaluation requires --live and an explicit model ID")
        cases = [read_case(path) for path in paths]
        withheld = {
            case.scenario.scenario_id
            for case, _, _ in cases
            if case and case.scenario.metadata.split == "held_out"
        }
        if withheld:
            visible = {
                case.scenario.scenario_id
                for case, _, _ in cases
                if case and case.scenario.scenario_id not in withheld
            }
            if visible and config.model.script:
                raise ValueError("held-out cases cannot share an unscoped development script")
            scoped = {
                name: {sid: value for sid, value in getattr(config, name).items() if sid in visible}
                for name in ("scripts", "annotations", "harnesses", "write_scopes")
            }
            config = config.model_copy(
                update={**scoped, "model": config.model.model_copy(update={"script": []})}
            )
        cases = [
            (None, fingerprint, "held_out_access_not_enabled")
            if case and case.scenario.scenario_id in withheld
            else (None, fingerprint, "sensitive_scenario_rejected")
            if case and self.store.contains_sensitive(case.model_dump(mode="json"))
            else (case, fingerprint, problem)
            for case, fingerprint, problem in cases
        ]
        ids = [
            case.scenario.scenario_id if case else "invalid_" + fingerprint[:16]
            for case, fingerprint, _ in cases
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scenario IDs; use repeats for repeated trials")
        study_validation = None
        if config.study is not None:
            from agent_reliability_lab.research.contracts import Reference
            from agent_reliability_lab.research.persistence import ResearchStore

            reference = Reference.model_validate(config.study["reference"])
            research = ResearchStore(self.engine, config.study.get("scope", "research"))
            study = research.validate_study(
                reference,
                ids,
                accept_declared_reviewers=config.study.get("accept_declared_reviewers") is True,
            )
            if study.evaluator_version != config.experimental_evaluator:
                raise ValueError("preregistered evaluator mismatch")
            if study.model != config.model.model_dump(mode="json"):
                raise ValueError("preregistered model mismatch")
            if study.budget_limits != config.budgets.model_dump(mode="json"):
                raise ValueError("preregistered execution budget mismatch")
            if study.sample_size != len(ids) * config.repeats:
                raise ValueError("preregistered sample size mismatch")
            variants = study.configurations.get("variants", [study.configurations])
            if dict(defense=config.defense, transport=config.transport) not in variants:
                raise ValueError("preregistered configuration mismatch")
            split = research.get(study.split)
            planned = {item.scenario_id: item for item in split.templates}
            for sid, (_case, fingerprint, problem) in zip(ids, cases, strict=True):
                if problem or planned[sid].content_hash != fingerprint:
                    raise ValueError("preregistered scenario content mismatch")
            for ref in study.oracles:
                oracle = research.get(ref)
                if oracle.scenario_hash != planned[oracle.scenario_id].content_hash:
                    raise ValueError("preregistered oracle scenario mismatch")
                if config.annotations.get(oracle.scenario_id, OracleSpec()) != oracle.scoring_rules:
                    raise ValueError("preregistered oracle rules mismatch")
            study_validation = dict(
                reference=reference.model_dump(mode="json"),
                mode=study.mode,
                validated_at=now().isoformat(),
                review_statuses=[research.review_status(ref) for ref in study.oracles],
                evaluator_audit_reference=study.evaluator_audit_reference,
            )
            if study.mode == "confirmatory" and config.model.provider == "fake":
                raise ValueError(
                    "scripted infrastructure trials cannot be confirmatory model evidence"
                )
        await self.store.initialize()
        manifest = {
            "schema_version": "1.0",
            "config": config.model_dump(mode="json"),
            "provenance": provenance(config),
            "created_at": now().isoformat(),
            "cases": [
                {"scenario_id": sid, "scenario_hash": fingerprint, "validation_error": problem}
                for sid, (_, fingerprint, problem) in zip(ids, cases, strict=True)
            ],
            "purpose": "scripted_infrastructure_validation"
            if config.model.provider == "fake"
            else "live_evaluation",
        }
        if study_validation is not None:
            manifest["study_validation"] = study_validation
        if demonstration:
            manifest["demonstration"] = True
        if benchmark_context is not None:
            manifest["benchmark"] = benchmark_context
        experiment_id = self.store.create_experiment(manifest)
        experiment = self.store.experiment(experiment_id)
        mode = "scripted" if config.model.provider == "fake" else "live"
        for case, fingerprint, problem in cases:
            scenario = case.scenario if case else None
            oracle = (
                config.annotations.get(scenario.scenario_id, case.oracle)
                if scenario
                else OracleSpec()
            )
            for trial_index in range(1, config.repeats + 1):
                meta = self.store.create_trial(
                    experiment_id, scenario, fingerprint, oracle, trial_index, mode
                )
                reason = problem
                if oracle.scenario_hash is not None and oracle.scenario_hash != fingerprint:
                    reason = "oracle_scenario_hash_mismatch"
                if scenario and scenario.injections and reason is None:
                    reason = "injection_sidecar_not_enabled"
                harness = config.harnesses.get(scenario.scenario_id) if scenario else None
                if harness:
                    if harness.scenario_hash != fingerprint or any(
                        item.scenario_id != scenario.scenario_id
                        or item.tool not in scenario.tools.available
                        for item in [*harness.faults, *harness.attacks]
                    ):
                        reason = "harness_scenario_binding_mismatch"
                    elif reason == "injection_sidecar_not_enabled":
                        # Explicit sidecar activates legacy declarations; defaults remain frozen.
                        if all(harness.covers_legacy(item) for item in scenario.injections):
                            reason = None
                        else:
                            reason = "harness_scenario_binding_mismatch"
                script = None
                if scenario and config.model.provider == "fake":
                    script = config.scripts.get(
                        scenario.scenario_id,
                        config.model.script or development_script(scenario.scenario_id),
                    )
                    if script is None and reason is None:
                        reason = "no_scripted_plan_configured"
                if reason:
                    status = (
                        "invalid_scenario"
                        if (problem and problem != "held_out_access_not_enabled")
                        or reason
                        in {"oracle_scenario_hash_mismatch", "harness_scenario_binding_mismatch"}
                        else "not_executed"
                    )
                    self.store.save_score(
                        excluded(
                            meta,
                            oracle,
                            status,
                            reason,
                            experimental_evaluator=config.experimental_evaluator,
                            experiment=experiment,
                        )
                    )
                    self.store.update_trial(meta["trial_id"], state="excluded", completed_at=now())
                    continue
                await self._trial(
                    scenario,
                    oracle,
                    config,
                    meta,
                    script,
                    live,
                    model_factory,
                    execution_options or {},
                    experiment,
                )
        return experiment_id

    async def _trial(
        self, scenario, oracle, config, meta, script, live, model_factory, options, experiment
    ):
        trial_id = meta["trial_id"]
        sandbox = None
        result = None
        evidence = None
        try:
            run_id = "eval_" + uuid.uuid4().hex[:27]
            sandbox = self.manager.provision(run_id, from_scenario(scenario), scenario.tools)
            with sandbox.transaction() as (_, registry):
                marker = registry["marker"]
            self.store.update_trial(
                trial_id,
                sandbox_run_id=run_id,
                ownership_marker=marker,
                cleanup={"status": "deferred", "reason": "execution_not_completed"},
            )
            initial = capture_initial(sandbox)
            agent_config = trial_agent_config(
                scenario,
                config,
                run_id,
                experiment["manifest"]["provenance"]["source_commit"],
                script,
            )
            host = AgentExecution(self.engine)
            async with ToolSession(self.engine, host.launch(agent_config), agent_config) as session:
                catalog = session.catalog
            if not set(scenario.tools.available) <= {tool["name"] for tool in catalog}:
                raise ValueError("declared tool is absent from discovery")
            execution_id = await host.create(scenario.user_request, agent_config)
            meta["execution_id"] = execution_id
            self.store.update_trial(
                trial_id, execution_id=execution_id, state="running", started_at=now()
            )
            started = time.perf_counter()
            model = model_factory(agent_config.model) if model_factory else None
            result = await host.run(
                execution_id, agent_config, model=model, live_opt_in=live, **options
            )
            duration = time.perf_counter() - started
            evidence = collect(self.engine, sandbox, execution_id, initial, catalog, duration)
            evidence.trial_binding = dict(
                trial_id=trial_id,
                experiment_id=meta["experiment_id"],
                scenario_id=scenario.scenario_id,
                scenario_hash=meta["scenario_hash"],
                execution_id=execution_id,
                sandbox_run_id=run_id,
                marker=evidence.marker,
                seed_hash=evidence.seed_hash,
            )
            if scenario.scenario_id in config.harnesses:
                harness = config.harnesses[scenario.scenario_id]
                evidence.experimental = {
                    "version": "1.0",
                    "model_visibility_capture": True,
                    "harness": harness.model_dump(mode="json"),
                    "harness_hash": digest(harness.model_dump(mode="json")),
                    "runtime_hash": digest(harness.runtime().model_dump(mode="json")),
                    "defense": agent_config.defense.model_dump(mode="json"),
                    "pairing_id": config.pairing_id,
                    "pair_key": f"{scenario.scenario_id}:{meta['trial_index']}",
                }
            self.store.save_evidence(trial_id, evidence)
            if result.status == "failed" and result.reason == "execution_error":
                scored = excluded(
                    meta,
                    oracle,
                    "infrastructure_failure",
                    "agent_host_execution_error",
                    experimental_evaluator=config.experimental_evaluator,
                    experiment=experiment,
                    evidence=evidence,
                )
            else:
                scored = score(
                    scenario,
                    oracle,
                    evidence,
                    meta,
                    config.prices,
                    experimental_evaluator=config.experimental_evaluator,
                    experiment=experiment,
                )
            self.store.save_score(scored)
        except Exception as error:
            self.store.save_score(
                excluded(
                    meta,
                    oracle,
                    "infrastructure_failure",
                    f"evaluation_infrastructure_{type(error).__name__}",
                    experimental_evaluator=config.experimental_evaluator,
                    experiment=experiment,
                    evidence=evidence,
                )
            )
            self.store.update_trial(trial_id, state="failed", completed_at=now())
        finally:
            if sandbox is not None:
                if result is None and meta.get("execution_id") or result and result.resume_eligible:
                    self.store.update_trial(
                        trial_id, cleanup={"status": "deferred", "reason": "incomplete_execution"}
                    )
                else:
                    self.cleanup(trial_id)

    def cleanup(self, trial_id: str) -> dict:
        trial = self.store.trial(trial_id)
        if trial["cleanup"]["status"] == "cleaned":
            return trial["cleanup"]
        run_id, marker = trial["sandbox_run_id"], trial["ownership_marker"]
        if not run_id or not run_id.startswith("eval_") or not marker:
            return {"status": "deferred", "reason": "not_a_runner_owned_resource"}
        try:
            if trial["execution_id"]:
                host = AgentExecution(self.engine)
                with host.store.claim(trial["execution_id"]):
                    if host.store.get(trial["execution_id"])["status"] not in TERMINAL:
                        raise ValueError("execution_is_incomplete")
                    self.manager.cleanup(run_id, expected_marker=marker)
            else:
                self.manager.cleanup(run_id, expected_marker=marker)
            outcome = {"status": "cleaned", "at": now().isoformat()}
        except Exception as error:
            outcome = {"status": "deferred", "reason": f"cleanup_{type(error).__name__}"}
        self.store.update_trial(trial_id, cleanup=outcome)
        return outcome

    def rescore(
        self,
        trial_id: str,
        oracle: OracleSpec | None = None,
        *,
        experimental_evaluator: str | None = None,
    ):
        trial = self.store.trial(trial_id)
        if trial["evidence"] is None or trial["scenario"] is None:
            raise ValueError("frozen evidence and a valid scenario are required for re-scoring")
        scenario = Scenario.model_validate_json(json.dumps(trial["scenario"]))
        selected = oracle or OracleSpec.model_validate(trial["oracle"])
        if selected.scenario_hash and selected.scenario_hash != trial["scenario_hash"]:
            raise ValueError("oracle scenario hash mismatch")
        experiment = self.store.experiment(trial["experiment_id"])
        if experimental_evaluator == "1.7.0":
            from agent_reliability_lab.evaluation.capture_v170 import score_capture

            result = score_capture(
                scenario, selected, trial["evidence"], trial["metadata"], experiment
            )
            self.store.save_score(result)
            return result
        manifest = experiment["manifest"]
        config = ExperimentConfig.model_validate_json(json.dumps(manifest["config"]))
        result = score(
            scenario,
            selected,
            Evidence.model_validate_json(json.dumps(trial["evidence"])),
            trial["metadata"],
            config.prices,
            experimental_evaluator=config.experimental_evaluator
            if experimental_evaluator is None
            else experimental_evaluator,
            experiment=experiment,
        )
        self.store.save_score(result)
        return result
