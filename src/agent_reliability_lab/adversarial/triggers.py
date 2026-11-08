"""Logical dispatch ordinals, independent of wall time and physical UUID values."""

import sqlalchemy as sa

from agent_reliability_lab.agent import tables as t


def subset(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and subset(value, actual[key]) for key, value in expected.items()
        )
    return type(expected) is type(actual) and expected == actual


def matching_ordinal(store, execution_id: str, spec) -> int:
    with store.engine.connect() as connection:
        arguments = connection.execute(
            sa.select(t.operations.c.arguments)
            .join(t.attempts, t.attempts.c.proposal_id == t.operations.c.proposal_id)
            .where(t.operations.c.execution_id == execution_id, t.operations.c.tool == spec.tool)
        ).scalars()
        return sum(subset(spec.trigger.arguments, value) for value in arguments)


def fires(trigger, ordinal: int) -> bool:
    return trigger.occurrence <= ordinal < trigger.occurrence + trigger.max_activations
