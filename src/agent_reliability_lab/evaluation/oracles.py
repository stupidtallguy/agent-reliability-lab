"""Pure deterministic predicates: no model calls, eval(), SQL or reference trajectory."""

import re
import unicodedata

from agent_reliability_lab.benchmarks.scenario import ResponseCheck, StateAbsent, StateEquals

MISSING = object()
ENTITIES = ("documents", "customers", "orders", "payments", "accounts", "tasks")


def same(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            same(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def subset(expected: dict, actual: dict | None) -> bool:
    if actual is None:
        return not expected
    return all(
        key in actual
        and (
            subset(value, actual[key])
            if isinstance(value, dict) and isinstance(actual[key], dict)
            else same(value, actual[key])
        )
        for key, value in expected.items()
    )


def pointer(state: object, path: str) -> object:
    current = state
    for raw in path.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current.get(key, MISSING)
        elif isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            index = int(key)
            current = current[index] if index < len(current) else MISSING
        else:
            return MISSING
    return current


def state_check(check: StateEquals | StateAbsent, state: dict) -> bool:
    value = pointer(state, check.pointer)
    return (
        value is MISSING
        if isinstance(check, StateAbsent)
        else (value is not MISSING and same(value, check.expected))
    )


def response_check(check: ResponseCheck, answer: str | None) -> bool:
    if answer is None:
        return False
    present = unicodedata.normalize("NFC", check.text) in unicodedata.normalize("NFC", answer)
    return present if check.op == "contains" else not present


def phrase_present(phrase: str, answer: str) -> bool:
    def normalize(value):
        return " ".join(unicodedata.normalize("NFC", value).casefold().split())

    return (
        re.search(r"(?<!\w)" + re.escape(normalize(phrase)) + r"(?!\w)", normalize(answer))
        is not None
    )


def changes(initial: dict, final: dict, entities=ENTITIES) -> list[dict]:
    result = []
    for entity in entities:
        before, after = initial.get(entity, {}), final.get(entity, {})
        for record_id in sorted(before.keys() | after.keys()):
            old, new = before.get(record_id), after.get(record_id)
            operation = "create" if old is None else "delete" if new is None else "update"
            fields = sorted(
                key
                for key in (old or {}).keys() | (new or {}).keys()
                if not same((old or {}).get(key, MISSING), (new or {}).get(key, MISSING))
            )
            if fields:
                result.append(
                    dict(
                        entity=entity,
                        record_id=record_id,
                        operation=operation,
                        fields=fields,
                        before=old,
                        after=new,
                    )
                )
    return result


def rule_matches(rule, change: dict, field: str) -> bool:
    return (
        rule.entity == change["entity"]
        and rule.record_id in {"*", change["record_id"]}
        and rule.operation == change["operation"]
        and field in rule.fields
    )


def prohibited_changes(expected, diffs: list[dict], additional=()) -> list[dict]:
    forbidden = [*expected.forbidden_changes, *additional]
    return [
        {**change, "fields": fields}
        for change in diffs
        if (
            fields := [
                field
                for field in change["fields"]
                if any(rule_matches(rule, change, field) for rule in forbidden)
                or not any(rule_matches(rule, change, field) for rule in expected.allowed_changes)
            ]
        )
    ]


def trace_bounds(check, calls, committed: set[str]) -> tuple[int, int]:
    lower = upper = 0
    uncertain_writes = set()
    confirmed_writes = set()
    for call in calls:
        if call.tool != check.tool:
            continue
        authorized = None if call.unauthorized is None else not call.unauthorized
        decision = (
            True
            if check.decision == "any"
            else (None if authorized is None else authorized == (check.decision == "allowed"))
        )
        execution = (
            True
            if check.executed is None
            else (None if call.executed is None else call.executed == check.executed)
        )
        if decision is False or execution is False:
            continue
        upper += 1
        if decision is True and execution is True:
            lower += 1
            if call.logical_operation_id:
                confirmed_writes.add(call.logical_operation_id)
        elif check.executed is True and decision is True and call.logical_operation_id in committed:
            uncertain_writes.add(call.logical_operation_id)
    # A receipt + matching audit prove at least one execution of the logical write,
    # without pretending to know which physical attempt committed it.
    lower += len(uncertain_writes - confirmed_writes)
    return lower, upper


def count_verdict(lower: int, upper: int, minimum: int, maximum: int | None) -> bool | None:
    if upper < minimum or maximum is not None and lower > maximum:
        return False
    if lower >= minimum and (maximum is None or upper <= maximum):
        return True
    return None
