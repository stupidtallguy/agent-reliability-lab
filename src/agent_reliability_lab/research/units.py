"""An experimental unit is a distinct pair of trials AND their executions."""


class InvalidExperimentalUnit(ValueError):
    code = "invalid_experimental_unit"

    def __init__(self, reason, pair_id):
        self.exclusions = [dict(pair_id=pair_id, reason=reason)]
        super().__init__(reason)


def validate_units(rows):
    pairs, trials, executions = set(), set(), set()
    for row in rows:
        pair_id = row["pair_id"]
        ids = (row.get("baseline_trial_id"), row.get("guarded_trial_id"))
        if row.get("verified") is True and any(
            not isinstance(row.get(key), str) or not row[key]
            for key in (
                "baseline_trial_id",
                "guarded_trial_id",
                "baseline_execution_id",
                "guarded_execution_id",
            )
        ):
            raise InvalidExperimentalUnit("missing_trial_or_execution_identity", pair_id)
        current = [item for item in ids if item is not None]
        actual = [row.get("baseline_execution_id"), row.get("guarded_execution_id")]
        actual = [item for item in actual if item is not None]
        if ids in pairs:
            raise InvalidExperimentalUnit("duplicate_underlying_trial_pair", pair_id)
        if len(current) != len(set(current)) or trials.intersection(current):
            raise InvalidExperimentalUnit("reused_trial_identity", pair_id)
        if len(actual) != len(set(actual)) or executions.intersection(actual):
            raise InvalidExperimentalUnit("reused_execution_identity", pair_id)
        pairs.add(ids)
        trials.update(current)
        executions.update(actual)
