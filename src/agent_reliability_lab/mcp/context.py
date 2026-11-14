"""Host-only launch identity, signed write metadata and sandbox-incarnation binding."""

import hashlib
import hmac
import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Annotated

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy.engine import Engine

from agent_reliability_lab.benchmarks.scenario import Contract, Identifier
from agent_reliability_lab.opsdesk import tables as t
from agent_reliability_lab.opsdesk.contracts import ActorContext, ServiceError
from agent_reliability_lab.opsdesk.database import Sandbox, SandboxManager, schema_for
from agent_reliability_lab.opsdesk.services import OpsDeskService
from agent_reliability_lab.reliability.notifications import TOOL, NotificationLab

OPERATION_META = "opsdesk.lab/operation"


class LaunchConfig(Contract):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    run_id: str
    actor_id: Identifier
    tenant_id: Identifier
    signing_key: SecretStr

    @field_validator("run_id")
    @classmethod
    def safe_run(cls, value: str) -> str:
        schema_for(value)
        return value

    @field_validator("signing_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[0-9a-f]{64}", value.get_secret_value()):
            raise ValueError("launch signing key must be 32 random bytes encoded as lowercase hex")
        return value

    @classmethod
    def from_env(cls) -> "LaunchConfig":
        return cls(
            run_id=os.environ.get("OPSDESK_MCP_RUN_ID", ""),
            actor_id=os.environ.get("OPSDESK_MCP_ACTOR_ID", ""),
            tenant_id=os.environ.get("OPSDESK_MCP_TENANT_ID", ""),
            signing_key=SecretStr(os.environ.get("OPSDESK_MCP_SIGNING_KEY", "")),
        )

    def child_env(self) -> dict[str, str]:
        """SDK adds its small platform environment; do not forward unrelated secrets."""
        return {
            "OPSDESK_DATABASE_URL": os.environ["OPSDESK_DATABASE_URL"],
            "OPSDESK_ALLOW_SANDBOX": os.environ.get("OPSDESK_ALLOW_SANDBOX", ""),
            "OPSDESK_MCP_RUN_ID": self.run_id,
            "OPSDESK_MCP_ACTOR_ID": self.actor_id,
            "OPSDESK_MCP_TENANT_ID": self.tenant_id,
            "OPSDESK_MCP_SIGNING_KEY": self.signing_key.get_secret_value(),
        }


class LogicalOperation(Contract):
    """Allocated/persisted by trusted host code, never supplied as a tool argument."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    operation_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]

    @classmethod
    def new(cls) -> "LogicalOperation":
        return cls(operation_id=uuid.uuid4().hex)


class OperationProof(Contract):
    operation_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    signature: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def operation_identity(config: LaunchConfig, tool: str, operation_id: str) -> dict:
    return {
        "run": config.run_id,
        "actor": config.actor_id,
        "tenant": config.tenant_id,
        "tool": tool,
        "operation": operation_id,
    }


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sign_operation(
    config: LaunchConfig, tool: str, arguments: dict, operation: LogicalOperation
) -> dict:
    identity = operation_identity(config, tool, operation.operation_id)
    signature = hmac.new(
        bytes.fromhex(config.signing_key.get_secret_value()),
        canonical({**identity, "arguments": arguments}),
        hashlib.sha256,
    ).hexdigest()
    return {OPERATION_META: {"operation_id": operation.operation_id, "signature": signature}}


def receipt_key(identity: dict) -> str:
    """Public pure mapping shared by proof verification and evidence reconciliation."""
    return "mcp_" + hashlib.sha256(canonical(identity)).hexdigest()


def service_key(config: LaunchConfig, tool: str, arguments: dict, meta: dict | None) -> str:
    try:
        proof = OperationProof.model_validate((meta or {}).get(OPERATION_META))
        operation = LogicalOperation(operation_id=proof.operation_id)
        expected = sign_operation(config, tool, arguments, operation)[OPERATION_META]["signature"]
        if not hmac.compare_digest(proof.signature, expected):
            raise ValueError("invalid proof")
    except (ValueError, TypeError):
        raise ServiceError("unauthorized", "A trusted logical operation is required.") from None
    return receipt_key(operation_identity(config, tool, proof.operation_id))


@dataclass(frozen=True)
class BoundContext:
    config: LaunchConfig
    sandbox: Sandbox
    service: OpsDeskService
    marker: str
    fixture_id: str
    fixture_version: str
    seed_hash: str

    @classmethod
    def bind(cls, engine: Engine, config: LaunchConfig) -> "BoundContext":
        sandbox = SandboxManager(engine).open(config.run_id)
        with sandbox.transaction() as (connection, registry):
            role = connection.execute(
                sa.select(t.actors.c.role).where(
                    t.actors.c.actor_id == config.actor_id, t.actors.c.tenant_id == config.tenant_id
                )
            ).scalar_one_or_none()
            if role not in {"viewer", "support_agent", "supervisor"}:
                raise ValueError("launch actor is not registered in this sandbox and tenant")
            fixture = registry["seed_spec"]["environment"]
            return cls(
                config,
                sandbox,
                OpsDeskService(sandbox),
                registry["marker"],
                fixture["fixture_id"],
                fixture["version"],
                registry["seed_hash"],
            )

    def invoke(self, tool: str, request: Contract) -> BaseModel:
        # Keep this shared lifecycle lock across the service's own transaction: no
        # cleanup/reprovision race may redirect an existing server to another scenario.
        with self.sandbox.transaction() as (_, registry):
            if registry["marker"] != self.marker or registry["seed_hash"] != self.seed_hash:
                raise ServiceError("unauthorized", "Bound sandbox context has changed.")
            actor = ActorContext(actor_id=self.config.actor_id, tenant_id=self.config.tenant_id)
            if tool == TOOL:
                try:
                    lab = NotificationLab(self.sandbox)
                except ValueError:
                    raise ServiceError(
                        "unauthorized", "Notification sandbox is unavailable."
                    ) from None
                return lab.queue(actor, request)
            return getattr(self.service, tool)(actor, request)
