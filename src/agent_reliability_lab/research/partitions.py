"""Composite, hash-pinned partition validation. No claim of semantic authorship."""


def validate_release(store, release):
    records = []
    families = {}
    scenarios, templates = set(), set()
    for name in ("development", "held_out"):
        reference = getattr(release, name)
        if reference.kind != "split":
            raise ValueError("partition requires a pinned split manifest")
        partition = store.get(reference)
        if partition.kind != "split":
            raise ValueError("partition reference has wrong artifact kind")
        for item in partition.templates:
            if item.split != name:
                raise ValueError("conflicting_partition_assignment")
            if item.scenario_id in scenarios:
                raise ValueError("duplicate_partition_scenario")
            if item.template_id in templates:
                raise ValueError("duplicate_partition_template")
            if families.setdefault(item.family_id, name) != name:
                raise ValueError("partition_family_overlap")
            scenarios.add(item.scenario_id)
            templates.add(item.template_id)
            records.append(item)

    def key(item):
        return item.scenario_id, item.template_id

    if sorted(records, key=key) != sorted(release.assignments, key=key):
        raise ValueError("partition_manifest_substitution_or_assignment_mismatch")
    return records
