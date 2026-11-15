"""Ed25519 publication authentication with an operator-managed trust directory."""

import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from agent_reliability_lab.opsdesk.fixtures import digest

PRIVATE_FILE = "OPSDESK_PUBLICATION_PRIVATE_KEY_FILE"
TRUST_DIR = "OPSDESK_PUBLICATION_TRUST_DIR"
SCHEMA = "opsdesk-reliability-publication/1.0.0"
ALGORITHM = "Ed25519"


def key_id(public):
    return digest(public.public_bytes_raw().hex())


def generate_key(private_file, trust_dir):
    """Create a new identity without replacing any configured key."""
    private_file = Path(private_file)
    trust_dir = Path(trust_dir)
    trust_dir.mkdir(parents=True, exist_ok=True)
    private_file.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    identity = key_id(public)
    try:
        with os.fdopen(
            os.open(private_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as f:
            f.write(private.private_bytes_raw())
        with (trust_dir / f"{identity}.pub").open("xb") as f:
            f.write(public.public_bytes_raw())
    except OSError:
        raise ValueError("could not create publication key files") from None
    return identity


def load_public(identity):
    if (
        not isinstance(identity, str)
        or len(identity) != 64
        or any(char not in "0123456789abcdef" for char in identity)
    ):
        raise ValueError("invalid publication key identifier")
    trust = os.environ.get(TRUST_DIR)
    if not trust:
        raise ValueError("publication trust directory is not configured")
    try:
        key = Ed25519PublicKey.from_public_bytes((Path(trust) / f"{identity}.pub").read_bytes())
    except (OSError, ValueError):
        raise ValueError("unknown or invalid publication verification key") from None
    if key_id(key) != identity:
        raise ValueError("publication verification key does not match its identifier")
    return key


def load_signer():
    path = os.environ.get(PRIVATE_FILE)
    if not path:
        raise ValueError("publication signing key is not configured")
    try:
        private = Ed25519PrivateKey.from_private_bytes(Path(path).read_bytes())
    except (OSError, ValueError):
        raise ValueError("publication signing key is unavailable or invalid") from None
    load_public(key_id(private.public_key()))
    return private


def manifest(document, snapshot, identity):
    binding = document["execution_evidence"]
    return {
        "schema": SCHEMA,
        "algorithm": ALGORITHM,
        "key_id": identity,
        "execution_id": document["execution_id"],
        "logical_operation_id": binding["logical_operation_id"],
        "notification_id": document["provider"]["notification_id"],
        "report_id": document["report_id"],
        "revision": document["revision"],
        "previous_report_id": document.get("previous_report_id"),
        "document_digest": digest(document),
        "snapshot_digest": digest(snapshot),
        "metrics_digest": digest(document["metrics"]),
        "publication_boundary": {
            "ledger_head": binding["ledger_head"],
            "provider_population_digest": digest(snapshot["provider"]),
        },
    }


def signed_bytes(body):
    return SCHEMA.encode("ascii") + b"\x00" + bytes.fromhex(digest(body))


def authenticate(document, snapshot, private):
    body = manifest(document, snapshot, key_id(private.public_key()))
    return {"manifest": body, "signature": private.sign(signed_bytes(body)).hex()}


def verify_attestation(document, snapshot, attestation):
    if not isinstance(attestation, dict) or set(attestation) != {"manifest", "signature"}:
        raise ValueError("missing or malformed publication attestation")
    body = attestation["manifest"]
    if not isinstance(body, dict) or (body.get("schema"), body.get("algorithm")) != (
        SCHEMA,
        ALGORITHM,
    ):
        raise ValueError("unsupported publication attestation contract")
    key = load_public(body.get("key_id"))
    try:
        key.verify(bytes.fromhex(attestation["signature"]), signed_bytes(body))
    except (InvalidSignature, TypeError, ValueError):
        raise ValueError("invalid publication signature") from None
    if digest(body) != digest(manifest(document, snapshot, body["key_id"])):
        raise ValueError("publication attestation does not match frozen report")
