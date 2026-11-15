"""Verify sealed catalog bytes and compare stimuli without emitting their contents."""

import hashlib
import hmac
import json
import os
import re
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from pydantic import ValidationError

from agent_reliability_lab.evaluation.contracts import ExperimentConfig
from agent_reliability_lab.evaluation.runner import read_case
from agent_reliability_lab.opsdesk.fixtures import digest
from agent_reliability_lab.platform.demo import assets, case_path
from agent_reliability_lab.research.contracts import SplitManifest
from agent_reliability_lab.research.heldout_contracts import PRIVATE_FORMAT, PrivateCatalog

PRIVATE_ENV = "OPSDESK_PRIVATE_HELDOUT_CATALOG"
PRIVATE_SUFFIX = ".opsdesk-heldout.json"
MAX_BYTES = 16 * 1024 * 1024
CHECKS = (
    "scenario_identity",
    "exact_content",
    "executable_input",
    "normalized_content",
    "template",
    "template_family",
    "attack_family",
    "reused_attack_payload",
    "lexical_similarity",
    "structural_similarity",
    "metadata",
)


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False, timeout=15
    )


def guard_index(root=Path(".")):
    files = _git(root, "ls-files", "-z")
    if files.returncode:
        raise ValueError("unable to inspect repository index for private catalogs")
    unsafe = sum(
        name.lower().endswith(PRIVATE_SUFFIX.encode())
        or name.lower().startswith(b".local/held-out/")
        for name in files.stdout.split(b"\0")
        if name
    )
    # Search staged text JSON, including files renamed away from the dedicated suffix.
    grep = _git(root, "grep", "--cached", "-I", "-l", "-F", PRIVATE_FORMAT, "--", "*.json")
    if unsafe or grep.returncode != 1:
        raise ValueError("tracked private catalog marker, path, or unverified Git index")


def _unique_keys(items):
    body = dict(items)
    if len(body) != len(items):
        raise ValueError("duplicate JSON fields")
    return body


def _private_path():
    setting = os.environ.get(PRIVATE_ENV)
    if not setting:
        raise ValueError("private catalog path is not configured")
    path = Path(setting).resolve(strict=True)
    if not path.is_file() or not path.name.lower().endswith(PRIVATE_SUFFIX):
        raise ValueError("private catalog must use its dedicated file suffix")
    repo = _git(path.parent, "rev-parse", "--show-toplevel")
    if repo.returncode == 0:
        root = Path(os.fsdecode(repo.stdout.strip())).resolve()
        relative = path.relative_to(root)
        if tuple(relative.parts[:2]) != (".local", "held-out"):
            raise ValueError("private catalog inside a checkout must be in .local/held-out")
        git_path = relative.as_posix()
        tracked = _git(root, "ls-files", "--error-unmatch", "--", git_path)
        ignored = _git(root, "check-ignore", "--", git_path)
        if tracked.returncode != 1 or ignored.returncode != 0:
            raise ValueError("private catalog path is tracked or is not Git-ignored")
    elif repo.returncode != 128 or any((p / ".git").exists() for p in path.parents):
        raise ValueError("unable to establish private catalog Git boundary")
    return path


def load_catalog(seal, *, authorized=False):
    if not authorized:
        raise ValueError("private catalog access requires explicit authorization")
    try:
        with _private_path().open("rb") as source:
            data = source.read(MAX_BYTES + 1)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        raise ValueError("private catalog could not be safely opened") from None
    if len(data) > MAX_BYTES:
        raise ValueError("private catalog exceeds the size limit")
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), seal.artifact_sha256):
        raise ValueError("private catalog fingerprint mismatch")
    try:
        parsed = json.loads(data, object_pairs_hook=_unique_keys)
        if not isinstance(parsed, dict) or parsed.get("format") != PRIVATE_FORMAT:
            raise ValueError("invalid private format")
        catalog = PrivateCatalog.model_validate(parsed)
    except (ValidationError, ValueError, RecursionError):
        raise ValueError("private catalog schema validation failed") from None
    if (
        catalog.benchmark_version != seal.benchmark_version
        or len(catalog.cases) != seal.held_out_count
    ):
        raise ValueError("private catalog contradicts its frozen version or count")
    return catalog


def _tokens(value):
    return tuple(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


def _normalize(value):
    if isinstance(value, str):
        return " ".join(_tokens(value))
    if isinstance(value, list):
        return sorted((_normalize(item) for item in value), key=digest)
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _shape(value, path, features):
    if isinstance(value, dict):
        for key, item in value.items():
            _shape(item, path + "/" + key, features)
    elif isinstance(value, list):
        for item in value:
            _shape(item, path + "/[]", features)
    else:
        features[path + ":" + type(value).__name__] += 1


@dataclass(frozen=True)
class Input:
    identity: str
    partition: str
    templates: frozenset
    families: frozenset
    attack_families: frozenset
    content_hash: str
    executable_hash: str
    normalized_hash: str
    request: tuple
    documents: tuple
    attacks: tuple
    shape: Counter
    metadata_ok: bool
    coverage: tuple = ()
    origin: str = "public"
    lineage: tuple = ()


def _input(
    scenario,
    partition,
    templates,
    families,
    attack_families,
    harness=None,
    *,
    coverage=(),
    origin="public",
    lineage=(),
    version_ok=True,
):
    data = scenario.model_dump(mode="json")
    fixture = {
        key: value for key, value in data["fixture"].items() if key not in {"fixture_id", "seed"}
    }
    fixture = {
        key: sorted(value, key=digest) if isinstance(value, list) else value
        for key, value in fixture.items()
    }
    runtime = harness.runtime().model_dump(mode="json") if harness else None
    actions = [*runtime["faults"], *runtime["attacks"]] if runtime else data["injections"]
    actions = [
        {
            key: value
            for key, value in item.items()
            if key
            not in {
                "scenario_id",
                "injection_id",
                "seed",
                "payload_reference",
                "payload_hash",
                "group",
            }
        }
        for item in actions
    ]
    executable = dict(
        request=data["user_request"],
        actor=data["actor"],
        fixture=fixture,
        tools={key: sorted(value) for key, value in data["tools"].items()},
        actions=sorted(actions, key=digest),
    )
    features = Counter(
        {
            "role:" + data["actor"]["role"]: 1,
            "category:" + data["category"]: 1,
            **{"tool:" + tool: 1 for tool in data["tools"]["available"]},
        }
    )
    _shape(fixture, "fixture", features)
    _shape(data["expected"], "expected", features)
    _shape(actions, "runtime", features)
    return Input(
        scenario.scenario_id,
        partition,
        frozenset(templates),
        frozenset(families),
        frozenset(attack_families),
        digest(data),
        digest(executable),
        digest(_normalize(executable)),
        _tokens(data["user_request"]),
        tuple(_tokens(d["content"]) for d in fixture["documents"]),
        tuple(_tokens(item["payload"]) for item in actions if "payload" in item),
        features,
        version_ok
        and scenario.metadata.split == ("held_out" if partition == "held_out" else "development")
        and len(coverage) == len(set(coverage)),
        tuple(coverage),
        origin,
        tuple(lineage),
    )


def comparison_inputs(dataset, workspace=None):
    """Include the 38 published development records and all pinned CP12 training/dev inputs."""
    root = assets(workspace)
    catalog = SplitManifest.model_validate_json(
        (root / "benchmarks/research/split-development.json").read_bytes()
    )
    config = ExperimentConfig.model_validate_json(
        (root / "benchmarks/evaluation/checkpoint5.json").read_bytes()
    )
    public = []
    for item in catalog.templates:
        case, fingerprint, problem = read_case(case_path(root, item.scenario_id))
        if problem or (
            fingerprint != item.content_hash
            or case.scenario.scenario_version != item.scenario_version
            or item.split != "development"
        ):
            raise ValueError("published development comparison catalog does not match its manifest")
        harness = config.harnesses.get(item.scenario_id)
        attack_labels = (
            [item.mechanism.split(":", 1)[1]] if item.mechanism.startswith("attack:") else []
        )
        if harness:
            if harness.scenario_hash != fingerprint:
                raise ValueError("published development harness fingerprint mismatch")
            attack_labels.extend(a.group for a in harness.attacks if a.group)
        public.append(
            _input(
                case.scenario,
                item.split,
                [item.template_id],
                [item.family_id],
                attack_labels,
                harness,
            )
        )
    for item in dataset.cases:
        if item.partition == "held_out":
            raise ValueError("comparison dataset may only contain training and development")
        public.append(
            _input(
                item.case.scenario,
                item.partition,
                [item.template_id],
                [item.template_family],
                [item.attack_family] if item.attack_family else [],
                item.harness,
            )
        )
    return public


def _profile_hash(item):
    return digest(
        [
            item.identity,
            item.partition,
            item.content_hash,
            item.executable_hash,
            item.normalized_hash,
            sorted(item.templates),
            sorted(item.families),
            sorted(item.attack_families),
            item.request,
            item.documents,
            item.attacks,
            item.shape,
            item.metadata_ok,
        ]
    )


def comparison_fingerprint(inputs):
    return digest(sorted({_profile_hash(item) for item in inputs}))


def _similarity(left, right):
    union = left | right
    if not union:
        return 0.0
    if isinstance(left, Counter):
        return sum((left & right).values()) / sum(union.values())
    return len(left & right) / len(union)


def _exact_text(left, right, minimum):
    return any(len(tokens) >= minimum for tokens in set(left) & set(right))


def _findings(a, b, policy):
    same_partition = a.partition == b.partition
    flags = {
        "scenario_identity": a.identity == b.identity,
        "exact_content": a.content_hash == b.content_hash,
        "executable_input": a.executable_hash == b.executable_hash,
        "normalized_content": a.normalized_hash == b.normalized_hash
        or (
            not same_partition
            and (a.request == b.request or _exact_text(a.documents, b.documents, 1))
        ),
        "template": not same_partition and bool(a.templates & b.templates),
        "template_family": not same_partition and bool(a.families & b.families),
        "attack_family": not same_partition and bool(a.attack_families & b.attack_families),
        "reused_attack_payload": not same_partition and _exact_text(a.attacks, b.attacks, 0),
    }
    findings = [{"check": name} for name, enabled in flags.items() if enabled]
    if same_partition:
        return findings
    text_pairs = [(a.request, b.request), *((x, y) for x in a.attacks for y in b.attacks)]
    scores = [
        _similarity(set(x), set(y))
        for x, y in text_pairs
        if min(len(x), len(y)) >= policy.minimum_lexical_tokens
    ]
    lexical = max(scores, default=0.0)
    if lexical >= policy.lexical_threshold:
        findings.append({"check": "lexical_similarity", "score": round(lexical, 6)})
    structure = _similarity(a.shape, b.shape)
    if structure >= policy.structural_threshold:
        findings.append({"check": "structural_similarity", "score": round(structure, 6)})
    return findings


def audit_catalog(catalog, public, seal, policy):
    profiles = {_profile_hash(item): item for item in public}
    if digest(sorted(profiles)) != seal.comparison_hash:
        raise ValueError("frozen development/training comparison fingerprint mismatch")
    public = [profiles[key] for key in sorted(profiles)]
    private = [
        _input(
            p.scenario.case.scenario,
            p.scenario.partition,
            [p.scenario.template_id],
            [p.scenario.template_family],
            [p.scenario.attack_family] if p.scenario.attack_family else [],
            p.scenario.harness,
            coverage=p.coverage,
            origin=p.origin,
            lineage=(p.source, *p.lineage),
            version_ok=p.scenario.benchmark_version == catalog.benchmark_version
            and p.scenario.partition == "held_out",
        )
        for p in catalog.cases
    ]
    inputs = [*public, *private]
    labels = [digest([catalog.nonce, index, item.identity]) for index, item in enumerate(inputs)]
    excluded, counts, details = set(), Counter(), []

    def record(finding, *indices):
        counts[finding["check"]] += 1
        excluded.update(indices)
        if len(details) < 1000:
            details.append(
                {
                    **finding,
                    "case_refs": [labels[i] for i in indices],
                    "partitions": [inputs[i].partition for i in indices],
                }
            )

    for index, item in enumerate(inputs):
        if not item.metadata_ok:
            record({"check": "metadata"}, index)
    for (i, a), (j, b) in combinations(enumerate(inputs), 2):
        if j < len(public) and a.partition == b.partition:
            continue
        for finding in _findings(a, b, policy):
            record(finding, i, j)
        if a.identity in b.lineage or (i >= len(public) and b.identity in a.lineage):
            record({"check": "metadata"}, i, j)
    accepted = [case for i, case in enumerate(private, len(public)) if i not in excluded]
    return dict(
        audit_version=policy.audit_version,
        benchmark_version=seal.benchmark_version,
        dataset_fingerprint=seal.artifact_sha256,
        comparison_fingerprint=seal.comparison_hash,
        policy=policy.model_dump(mode="json"),
        passed=not excluded,
        comparison_counts=dict(
            Counter(x.partition for x in {(i.identity, i.partition): i for i in public}.values())
        ),
        held_out_cases=len(private),
        held_out_eligible=len(accepted),
        held_out_excluded=len(private) - len(accepted),
        eligible_template_families=len({name for case in accepted for name in case.families}),
        eligible_attack_families=len({name for case in accepted for name in case.attack_families}),
        private_origin_counts=dict(Counter(x.origin for x in private)),
        eligible_coverage=dict(Counter(tag for case in accepted for tag in case.coverage)),
        checks={name: dict(passed=not counts[name], findings=counts[name]) for name in CHECKS},
        excluded_case_refs=sorted(labels[i] for i in excluded if i >= len(public)),
        findings=details,
        findings_truncated=len(details) < sum(counts.values()),
        semantic_independence="not_established",
        human_review="not_performed",
        execution="disabled",
    )
