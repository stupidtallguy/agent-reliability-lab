from tests.remediation16.support import configuration as previous_configuration


def configuration(**updates):
    return previous_configuration().model_copy(
        update={"experimental_evaluator": "1.7.0", **updates}
    )


def facts(outcome=True, exposure=True, index=1):
    from agent_reliability_lab.evaluation.attack_outcomes_v170 import resolve_trial
    from agent_reliability_lab.evaluation.execution_facts import execution_facts
    from agent_reliability_lab.evaluation.versions import implementation_identity
    from tests.finalization.population_support import facts as base_facts

    t, r = base_facts(outcome, exposure, index, version="1.7.0")
    goal = r.experimental["objectives"][0]
    goal["injection_id"] = configuration().harnesses["attack_hijack"].attacks[0].injection_id
    goal["verified_exposure"] = exposure
    goal["attribution"]["status"] = (
        "verified_unexposed_completed"
        if exposure is False
        else "eligible_match"
        if outcome is True
        else "verified_non_match"
        if outcome is False
        else "indeterminate"
    )
    r.scoring_provenance.update(
        requested_evaluator_version="1.7.0",
        effective_evaluator_version="1.7.0",
        adversarial_source_hash="a" * 64,
        **implementation_identity(),
    )
    r.experimental["attack_resolution"] = resolve_trial(r, facts=execution_facts(t["evidence"]))
    return t, r


def store(rows, repeats=1):
    from tests.finalization.population_support import Store

    return Store(rows, repeats, version="1.7.0")
