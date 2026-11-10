"""Typed experiment metadata boundary; malformed plans never become empty plans."""

import json
import re

from pydantic import ValidationError

from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.opsdesk.fixtures import digest


class ManifestError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_manifest(experiment):
    if not isinstance(experiment, dict):
        raise ManifestError("experiment_envelope_unavailable")
    manifest = experiment.get("manifest")
    if not isinstance(manifest, dict):
        raise ManifestError("malformed_experiment_manifest")
    expected = experiment.get("manifest_hash")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ManifestError("missing_or_malformed_manifest_hash")
    if digest(manifest) != expected:
        raise ManifestError("contradictory_manifest_hash")
    if not isinstance(manifest.get("config"), dict):
        raise ManifestError("missing_or_malformed_experiment_configuration")
    try:
        config = ExperimentConfig.model_validate_json(json.dumps(manifest["config"]))
    except (ValidationError, ValueError, TypeError):
        raise ManifestError("invalid_experiment_configuration") from None
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ManifestError("missing_or_malformed_trial_plan")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("scenario_id"), str):
            raise ManifestError("malformed_planned_case_identity")
        if not isinstance(case.get("scenario_hash"), str) or not re.fullmatch(
            r"[a-f0-9]{64}", case["scenario_hash"]
        ):
            raise ManifestError("malformed_planned_scenario_hash")
        if case["scenario_id"] in seen:
            raise ManifestError("duplicate_planned_scenario")
        seen.add(case["scenario_id"])
        harness = config.harnesses.get(case["scenario_id"])
        if harness and harness.scenario_hash != case["scenario_hash"]:
            raise ManifestError("contradictory_planned_harness_hash")
    return manifest, config
