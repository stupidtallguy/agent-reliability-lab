"""Candidate raw frozen-capture boundary for append-only rescoring."""

import json

from pydantic import ValidationError

from agent_reliability_lab.evaluation.contracts import Evidence
from agent_reliability_lab.evaluation.manifests import ManifestError, validate_manifest
from agent_reliability_lab.evaluation.scoring import excluded, score
from agent_reliability_lab.opsdesk.fixtures import digest


def score_capture(scenario, oracle, capture, meta, experiment):
    try:
        _, config = validate_manifest(experiment)
    except ManifestError as error:
        result = excluded(
            meta, oracle, "evidence_error", error.code, experimental_evaluator="1.7.0"
        )
    else:
        try:
            evidence = Evidence.model_validate_json(json.dumps(capture))
        except ValidationError:
            result = excluded(
                meta,
                oracle,
                "evidence_error",
                "malformed_frozen_evidence",
                experimental_evaluator="1.7.0",
                experiment=experiment,
            )
        else:
            return score(
                scenario,
                oracle,
                evidence,
                meta,
                config.prices,
                experimental_evaluator="1.7.0",
                experiment=experiment,
            )
    result.evidence_hash = digest(capture)
    result.evidence_reference = f"opsdesk-eval://trials/{meta['trial_id']}/evidence"
    return result
