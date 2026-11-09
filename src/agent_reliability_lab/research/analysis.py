"""Analysis reads hash-pinned pairs and selected persisted scoring revisions."""

from agent_reliability_lab.evaluation.selection import compatible, select
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.research.statistics import paired_summary


def analyze(store, pair_references, split_reference, evaluator_version, *, seed=0):
    split = store.get(split_reference)
    if split.kind != "split":
        raise ValueError("analysis requires a frozen split catalog")
    families = {t.scenario_id: t.family_id for t in split.templates}
    rows = []
    selected = []
    groups, configurations, environments = set(), set(), set()
    score_references = []
    for reference in pair_references:
        pair = store.get(reference)
        if pair.kind != "pair":
            raise ValueError("analysis requires frozen pairing records")
        groups.add(pair.pair_group)
        trial = store.evaluations.trial(pair.baseline_trial_id)
        manifest = store.evaluations.experiment(trial["experiment_id"])["manifest"]
        configurations.add(
            digest(
                {k: v for k, v in manifest["config"].items() if k not in {"defense", "pairing_id"}}
            )
        )
        environments.add(digest(manifest["provenance"]))
        outcomes = []
        for trial_id in (pair.baseline_trial_id, pair.guarded_trial_id):
            if trial_id is None:
                outcomes.append(None)
                continue
            trial = store.evaluations.trial(trial_id)
            cohort = select(
                store.evaluations,
                store.evaluations.experiment(trial["experiment_id"]),
                store.evaluations.list_trials(experiment_id=trial["experiment_id"]),
                evaluator_version=evaluator_version,
                trial_ids=[trial_id],
            )
            result = cohort.results[0] if cohort.results else None
            outcomes.append(result.objective_success if result and result.eligible else None)
            if result:
                selected.append(result)
                score_references.append(
                    dict(
                        scoring_id=result.scoring_id,
                        revision=cohort.revisions[result.scoring_id],
                        evidence_hash=result.evidence_hash,
                        evaluator_version=result.evaluator_version,
                        rules_hash=result.rules_hash,
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
        oracle = store.get(pair.oracle)
        if oracle.scenario_id not in families:
            raise ValueError("paired scenario absent from split catalog")
        rows.append(
            dict(
                pair_id=pair.identity,
                verified=pair.verification == "verified",
                scenario_id=oracle.scenario_id,
                family_id=families[oracle.scenario_id],
                baseline=outcomes[0],
                guarded=outcomes[1],
            )
        )
    if len(groups) > 1 or len(configurations) > 1 or len(environments) > 1:
        raise ValueError(
            "research analysis requires one compatible pair group/configuration/environment"
        )
    compatible(selected)
    summary = paired_summary(rows, seed=seed)
    # Family labels alone cannot establish independence; inference stays disabled by default.
    return dict(
        summary=summary,
        selected_scores=score_references,
        pairs=[ref.model_dump(mode="json") for ref in pair_references],
        split=split_reference.model_dump(mode="json"),
        evaluator_version=evaluator_version,
        rows=rows,
    )
