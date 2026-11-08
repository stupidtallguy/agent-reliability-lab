"""Safe tool errors; protocol framing errors remain the SDK's responsibility."""

import uuid

from agent_reliability_lab.mcp.contracts import SafeError
from agent_reliability_lab.opsdesk.contracts import ServiceError

MESSAGES = {
    "validation_error": "Arguments do not match the tool schema.",
    "not_found": "Record not found.",
    "permission_denied": "Operation is not permitted for this bound actor or context.",
    "approval_required": "This operation requires approval.",
    "version_conflict": "Task version has changed; read the task before a new operation.",
    "idempotency_conflict": "Logical operation was already used for different arguments.",
    "database_unavailable": "The sandbox database operation could not complete.",
    "internal_error": "The tool failed; consult developer logs with the correlation ID.",
    "response_too_large": "Result exceeds the response limit; request a smaller page.",
}
SERVICE_CODES = {
    "invalid_arguments": "validation_error",
    "constraint_violation": "validation_error",
    "unauthorized": "permission_denied",
    "not_found": "not_found",
    "approval_required": "approval_required",
    "version_conflict": "version_conflict",
    "idempotency_conflict": "idempotency_conflict",
    "storage_failure": "database_unavailable",
}


def safe_error(code: str, *, retryable: bool = False) -> SafeError:
    return SafeError(
        code=code, message=MESSAGES[code], retryable=retryable, correlation_id=uuid.uuid4().hex
    )


def service_error(error: ServiceError) -> SafeError:
    return safe_error(
        SERVICE_CODES.get(error.detail.code, "internal_error"),
        retryable=error.detail.retryable if error.detail.code == "storage_failure" else False,
    )
