"""Bind the sealed catalog, planning protocol and analysis plan to frozen references."""

import platform
from datetime import UTC, datetime

from agent_reliability_lab.research.heldout import (
    audit_catalog,
    comparison_fingerprint,
    comparison_inputs,
    load_catalog,
)
from agent_reliability_lab.research.heldout_contracts import (
    CatalogSeal,
    ConfirmatoryAnalysisPlan,
    ConfirmatoryProtocol,
)


def _get(store, ref, expected):
    item = store.get(ref)
    if item.kind != expected:
        raise ValueError("unexpected frozen benchmark reference kind")
    return item


def _predecessor(store, item):
    if (item.version == 1) != (item.supersedes is None):
        raise ValueError("amendments must pin their immediate predecessor")
    if item.supersedes:
        prior = _get(store, item.supersedes, item.kind)
        if (prior.identity, prior.version) != (item.identity, item.version - 1):
            raise ValueError("amendment predecessor identity or version differs")


def validate_design_references(store, item):
    if item.kind == "benchmark_catalog_seal":
        comparison = _get(store, item.reference_dataset, "benchmark_dataset")
        if (
            comparison.benchmark_version != item.benchmark_version
            or comparison_fingerprint(comparison_inputs(comparison)) != item.comparison_hash
        ):
            raise ValueError("seal comparison fingerprint or version differs")
    elif item.kind == "benchmark_confirmatory_protocol":
        seal = _get(store, item.catalog, "benchmark_catalog_seal")
        reference = _get(store, item.development_protocol, "benchmark_protocol")
        if reference.dataset != seal.reference_dataset:
            raise ValueError("development protocol and sealed comparison dataset differ")
        _predecessor(store, item)
    elif item.kind == "benchmark_analysis_plan":
        protocol = _get(store, item.protocol, "benchmark_confirmatory_protocol")
        if (
            item.catalog != protocol.catalog
            or item.alpha != protocol.power.alpha
            or item.simulation_seed != protocol.power.seed
            or item.order_seed != protocol.order_seed
        ):
            raise ValueError("analysis plan differs from the frozen protocol or catalog")
        _predecessor(store, item)


def draft_design(store, reference, identity, artifact_sha256, count, power):
    parent = _get(store, reference, "benchmark_protocol")
    dataset = _get(store, parent.dataset, "benchmark_dataset")
    metadata = dict(identity=identity, author=parent.author, created_at=datetime.now(UTC))
    seal = CatalogSeal(
        **metadata,
        benchmark_version=dataset.benchmark_version,
        reference_dataset=parent.dataset,
        comparison_hash=comparison_fingerprint(comparison_inputs(dataset)),
        artifact_sha256=artifact_sha256,
        held_out_count=count,
    )
    protocol = ConfirmatoryProtocol(
        **metadata,
        catalog=store.reference(seal),
        development_protocol=reference,
        **({"power": power} if power is not None else {}),
    )
    analysis = ConfirmatoryAnalysisPlan(
        **metadata,
        protocol=store.reference(protocol),
        catalog=protocol.catalog,
        python_version=platform.python_version(),
        alpha=protocol.power.alpha,
        simulation_seed=protocol.power.seed,
        order_seed=protocol.order_seed,
    )
    return {"catalog-seal": seal, "confirmatory-protocol": protocol, "analysis-plan": analysis}


def audit_registered(store, protocol_ref, *, authorized=False):
    if not authorized:
        raise ValueError("private catalog access requires explicit authorization")
    protocol = _get(store, protocol_ref, "benchmark_confirmatory_protocol")
    validate_design_references(store, protocol)
    seal = _get(store, protocol.catalog, "benchmark_catalog_seal")
    dataset = _get(store, seal.reference_dataset, "benchmark_dataset")
    public = comparison_inputs(dataset)
    if comparison_fingerprint(public) != seal.comparison_hash:
        raise ValueError("frozen development/training comparison fingerprint mismatch")
    report = audit_catalog(
        load_catalog(seal, authorized=authorized), public, seal, protocol.leakage
    )
    report["protocol"] = protocol_ref.model_dump(mode="json")
    report["catalog"] = protocol.catalog.model_dump(mode="json")
    return report
