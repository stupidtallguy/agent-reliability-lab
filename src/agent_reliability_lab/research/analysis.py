"""Pinned oracle/revision comparisons over unique underlying experimental units."""

from agent_reliability_lab.evaluation.selection import compatible, semantic_version
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.statistics import paired_summary
from agent_reliability_lab.research.units import validate_units


class AmbiguousScoreRevision(ValueError):
    code = "ambiguous_scoring_revision"


class IncompatibleComparisonRules(ValueError):
    code = "incompatible_comparison_rules"


def selected_score(store, trial_id, version, selection):
    choices = [
        (index, result)
        for index, result in enumerate(store.scores(trial_id), 1)
        if semantic_version(result) == version
    ]
    if selection is not None:
        if (
            not isinstance(selection, dict)
            or not selection
            or not set(selection) <= {"scoring_id", "revision"}
        ):
            raise ValueError("explicit score selection requires scoring_id and/or revision")
        if "revision" in selection and (
            type(selection["revision"]) is not int or selection["revision"] < 1
        ):
            raise ValueError("revision must be a positive integer")
        choices = [
            (revision, result)
            for revision, result in choices
            if ("revision" not in selection or selection["revision"] == revision)
            and ("scoring_id" not in selection or selection["scoring_id"] == result.scoring_id)
        ]
        if len(choices) != 1:
            raise ValueError("requested scoring revision is unavailable")
    if len(choices) > 1:
        raise AmbiguousScoreRevision("pin a scoring ID or revision for this trial")
    return choices[0] if choices else (None, None)


def analyze(
    store, pair_references, split_reference, evaluator_version, *, seed=0, score_selections=None
):
    from agent_reliability_lab.evaluation.versions import validate_selection

    if evaluator_version != "1.0.1":
        validate_selection(evaluator_version)
    split = store.get(split_reference)
    if split.kind == "dataset_release":
        from agent_reliability_lab.research.partitions import validate_release

        templates = validate_release(store, split)
    elif split.kind == "split":
        # Historical development-only analyses remain possible; this proves no held-out boundary.
        if any(t.split != "development" for t in split.templates):
            raise ValueError("held-out analysis requires a composite dataset release")
        templates = split.templates
    else:
        raise ValueError("analysis requires a frozen split catalog or dataset release")
    catalog = {t.scenario_id: t for t in templates}
    rows, selected, score_references = [], [], []
    groups, configurations, environments = set(), set(), set()
    selections = score_selections or {}
    seen_trials = set()
    for reference in pair_references:
        pair = store.get(reference)
        if pair.kind != "pair":
            raise ValueError("analysis requires frozen pairing records")
        oracle = store.get(pair.oracle)
        if oracle.kind != "oracle" or oracle.scenario_id not in catalog:
            raise IncompatibleComparisonRules("pair oracle absent from split catalog")
        template = catalog[oracle.scenario_id]
        if (oracle.scenario_hash, oracle.scenario_version) != (
            template.content_hash,
            template.scenario_version,
        ):
            raise IncompatibleComparisonRules("oracle and split scenario specifications differ")
        expected_rules = digest(oracle.scoring_rules.model_dump(mode="json"))
        groups.add(pair.pair_group)
        trial = store.evaluations.trial(pair.baseline_trial_id)
        manifest = store.evaluations.experiment(trial["experiment_id"])["manifest"]
        configurations.add(
            digest(
                {k: v for k, v in manifest["config"].items() if k not in {"defense", "pairing_id"}}
            )
        )
        environments.add(digest(manifest["provenance"]))
        outcomes, executions = [], []
        for trial_id in (pair.baseline_trial_id, pair.guarded_trial_id):
            if trial_id is None:
                outcomes.append(None)
                executions.append(None)
                continue
            seen_trials.add(trial_id)
            trial = store.evaluations.trial(trial_id)
            executions.append(trial.get("execution_id"))
            if (trial["scenario_id"], trial["scenario_version"], trial["scenario_hash"]) != (
                oracle.scenario_id,
                oracle.scenario_version,
                oracle.scenario_hash,
            ) or digest(trial["oracle"]) != expected_rules:
                raise IncompatibleComparisonRules("frozen trial differs from pinned pair oracle")
            revision, result = selected_score(
                store.evaluations, trial_id, evaluator_version, selections.get(trial_id)
            )
            if result and (
                result.rules_hash != expected_rules
                or digest(result.oracle_spec) != expected_rules
                or (result.scenario_id, result.scenario_version, result.scenario_hash)
                != (oracle.scenario_id, oracle.scenario_version, oracle.scenario_hash)
                or result.execution_id != trial.get("execution_id")
                or result.evidence_hash != trial.get("evidence_hash")
            ):
                raise IncompatibleComparisonRules(
                    "selected scoring revision violates pinned oracle"
                )
            outcomes.append(result.objective_success if result and result.eligible else None)
            if result:
                selected.append(result)
                score_references.append(
                    dict(
                        scoring_id=result.scoring_id,
                        trial_id=trial_id,
                        revision=revision,
                        evidence_hash=result.evidence_hash,
                        evaluator_version=result.evaluator_version,
                        rules_hash=result.rules_hash,
                        oracle_reference=pair.oracle.model_dump(mode="json"),
                        implementation_hashes={
                            k: result.scoring_provenance.get(k)
                            for k in (
                                "evaluator_source_hash",
                                "adversarial_source_hash",
                                "scoring_implementation_hash",
                                "dependency_lock_hash",
                            )
                        },
                    )
                )
        rows.append(
            dict(
                pair_id=pair.identity,
                verified=pair.verification == "verified",
                baseline_trial_id=pair.baseline_trial_id,
                guarded_trial_id=pair.guarded_trial_id,
                baseline_execution_id=executions[0],
                guarded_execution_id=executions[1],
                scenario_id=oracle.scenario_id,
                family_id=template.family_id,
                baseline=outcomes[0],
                guarded=outcomes[1],
            )
        )
    if set(selections) - seen_trials:
        raise ValueError("score selection references a trial outside the requested pairs")
    validate_units(rows)
    if len(groups) > 1 or len(configurations) > 1 or len(environments) > 1:
        raise ValueError(
            "research analysis requires one compatible pair group/configuration/environment"
        )
    compatible(selected)
    summary = paired_summary(rows, seed=seed)
    return dict(
        schema_version="1.1",
        experimental_unit="unique_trial_execution_pair_v1",
        summary=summary,
        selected_scores=score_references,
        pairs=[ref.model_dump(mode="json") for ref in pair_references],
        split=split_reference.model_dump(mode="json"),
        evaluator_version=evaluator_version,
        rows=rows,
        exclusions=[],
    )


def compare_versions(store, pairs, split, versions, *, policy, score_selections=None, seed=0):
    if policy != "separate_pinned_oracle_cohorts_v1" or len(set(versions)) != len(versions):
        raise ValueError("explicit separate-cohort comparison policy and unique versions required")
    return dict(
        comparison_policy=policy,
        pooled=False,
        warning="Different evaluator semantics; no pooled effect or denominator.",
        cohorts={
            version: analyze(
                store,
                pairs,
                split,
                version,
                seed=seed,
                score_selections=(score_selections or {}).get(version),
            )
            for version in versions
        },
    )
