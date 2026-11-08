"""Actual SDK in-memory protocol boundary, with no database dependency."""

import copy
from datetime import UTC, datetime

import jsonschema
import pytest
from mcp import Client, MCPError
from pydantic import SecretStr, ValidationError

from agent_reliability_lab.mcp.client import TrustedClient
from agent_reliability_lab.mcp.context import (
    OPERATION_META,
    LaunchConfig,
    LogicalOperation,
    service_key,
    sign_operation,
)
from agent_reliability_lab.mcp.servers import create_server
from agent_reliability_lab.opsdesk.contracts import CustomerView, DocumentView, ServiceError

pytestmark = pytest.mark.anyio
DOMAINS = {
    "documents": {"search_documents", "get_document"},
    "business": {"get_order", "get_customer", "list_customer_orders"},
    "tasks": {"list_tasks", "create_task", "update_task"},
}


@pytest.mark.parametrize("domain", DOMAINS)
async def test_discovery_exposes_only_domain_tools_and_strict_schemas(mock_binding, domain):
    async with Client(
        create_server(domain, mock_binding), raise_exceptions=True, cache=None
    ) as client:
        listing = await client.list_tools()
        assert client.protocol_version == "2026-07-28"
        assert {tool.name for tool in listing.tools} == DOMAINS[domain]
        for tool in listing.tools:
            assert tool.description and len(tool.description) < 200
            jsonschema.Draft202012Validator.check_schema(tool.input_schema)
            jsonschema.Draft202012Validator.check_schema(tool.output_schema)
            assert tool.input_schema["additionalProperties"] is False
            assert not {
                "actor_id",
                "tenant_id",
                "run_id",
                "idempotency_key",
                "operation_id",
            }.intersection(tool.input_schema["properties"])
            assert {"data", "error", "provenance"} <= tool.output_schema["properties"].keys()
    mock_binding.invoke.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"customer_id": "../escape"},
        {"customer_id": 3},
        {"customer_id": "customer_001", "actor_id": "supervisor_001"},
        {"customer_id": "customer_001", "tenant_id": "otherdesk"},
        {"customer_id": "customer_001", "run_id": "docker_probe_01"},
    ],
)
async def test_invalid_arguments_are_safe_errors_before_services(mock_binding, arguments):
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as client:
        result = await client.call_tool("get_customer", arguments)
        assert result.is_error
        assert result.structured_content["error"]["code"] == "validation_error"
        assert result.structured_content["data"] is None
        assert "../escape" not in result.model_dump_json()
    mock_binding.invoke.assert_not_called()


@pytest.mark.parametrize(
    "code,expected",
    [
        ("not_found", "not_found"),
        ("unauthorized", "permission_denied"),
        ("approval_required", "approval_required"),
        ("version_conflict", "version_conflict"),
        ("idempotency_conflict", "idempotency_conflict"),
        ("storage_failure", "database_unavailable"),
        ("invalid_arguments", "validation_error"),
        ("unrecognized", "internal_error"),
    ],
)
async def test_service_errors_use_allowlisted_messages(mock_binding, code, expected):
    mock_binding.invoke.side_effect = ServiceError(code, "SENSITIVE_SQL_AND_DSN", retryable=True)
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as client:
        result = await client.call_tool("get_customer", {"customer_id": "customer_001"})
        payload = result.structured_content
        assert result.is_error and payload["error"]["code"] == expected
        assert payload["error"]["retryable"] is (code == "storage_failure")
        assert len(payload["error"]["correlation_id"]) == 32
        assert "SENSITIVE_SQL_AND_DSN" not in result.model_dump_json()


async def test_unexpected_exception_details_stay_in_developer_logs(mock_binding, caplog):
    sentinel = "INTERNAL_PATH_PASSWORD_SQL_SENTINEL"
    mock_binding.invoke.side_effect = RuntimeError(sentinel)
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as client:
        result = await client.call_tool("get_customer", {"customer_id": "customer_001"})
        assert result.is_error
        assert result.structured_content["error"]["code"] == "internal_error"
        assert sentinel not in result.model_dump_json()
        assert any(record.exc_info for record in caplog.records)


async def test_bad_service_output_is_internal_error_not_input_error(mock_binding):
    mock_binding.invoke.return_value = DocumentView(
        document_id="policy_001",
        title="wrong DTO",
        content="data",
        category="policy",
        version=1,
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        trust_classification="untrusted",
    )
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as client:
        result = await client.call_tool("get_customer", {"customer_id": "customer_001"})
        assert result.structured_content["error"]["code"] == "internal_error"


async def test_success_schema_and_json_text_match(mock_binding):
    import json

    mock_binding.invoke.return_value = CustomerView(
        customer_id="customer_001",
        display_name="Test",
        email="test@customers.opsdesk.invalid",
        version=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as client:
        tool = next(
            tool for tool in (await client.list_tools()).tools if tool.name == "get_customer"
        )
        result = await client.call_tool("get_customer", {"customer_id": "customer_001"})
        assert not result.is_error
        jsonschema.validate(result.structured_content, tool.output_schema)
        assert json.loads(result.content[0].text) == result.structured_content
        assert result.structured_content["data"]["created_at"].endswith("Z")


async def test_unknown_tool_is_safe_protocol_error(mock_binding):
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as client:
        with pytest.raises(MCPError, match="Unknown tool"):
            await client.call_tool("arbitrary_sql", {"sql": "SENSITIVE_SQL"})
    mock_binding.invoke.assert_not_called()


async def test_output_and_argument_byte_limits(mock_binding):
    mock_binding.invoke.return_value = DocumentView(
        document_id="policy_001",
        title="Large",
        content="x" * 70000,
        category="policy",
        version=1,
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        trust_classification="untrusted",
    )
    async with Client(create_server("documents", mock_binding), raise_exceptions=True) as client:
        oversized = await client.call_tool("get_document", {"document_id": "policy_001"})
        assert oversized.structured_content["error"]["code"] == "response_too_large"
        mock_binding.invoke.reset_mock()
        invalid = await client.call_tool("search_documents", {"query": "x" * 20000})
        assert invalid.structured_content["error"]["code"] == "validation_error"
        mock_binding.invoke.assert_not_called()


async def test_write_requires_valid_host_metadata_and_rejects_key_argument(mock_binding):
    async with Client(create_server("tasks", mock_binding), raise_exceptions=True) as client:
        arguments = {"customer_id": "customer_001", "title": "Test"}
        result = await client.call_tool("create_task", arguments)
        assert result.structured_content["error"]["code"] == "permission_denied"
        proof = sign_operation(
            mock_binding.config, "create_task", arguments, LogicalOperation.new()
        )
        proof[OPERATION_META]["signature"] = "0" * 64
        result = await client.call_tool("create_task", arguments, meta=proof)
        assert result.structured_content["error"]["code"] == "permission_denied"
        result = await client.call_tool("create_task", {**arguments, "idempotency_key": "bypass"})
        assert result.structured_content["error"]["code"] == "validation_error"
    mock_binding.invoke.assert_not_called()


async def test_host_identity_signature_scope_and_stable_service_key(mock_binding):
    config = mock_binding.config
    operation = LogicalOperation.new()
    arguments = {"customer_id": "customer_001", "title": "Test"}
    proof = sign_operation(config, "create_task", arguments, operation)
    first = service_key(config, "create_task", arguments, proof)
    assert service_key(config, "create_task", copy.deepcopy(arguments), proof) == first
    assert (
        service_key(
            config,
            "create_task",
            {**arguments, "title": "Changed"},
            sign_operation(config, "create_task", {**arguments, "title": "Changed"}, operation),
        )
        == first
    )
    other = LogicalOperation.new()
    assert (
        service_key(
            config,
            "create_task",
            arguments,
            sign_operation(config, "create_task", arguments, other),
        )
        != first
    )
    for tool, args in [
        ("update_task", arguments),
        ("create_task", {**arguments, "title": "Changed"}),
    ]:
        with pytest.raises(ServiceError):
            service_key(config, tool, args, proof)
    changed = config.model_copy(update={"run_id": "other_run"})
    with pytest.raises(ServiceError):
        service_key(changed, "create_task", arguments, proof)
    assert LogicalOperation.model_validate_json(operation.model_dump_json()) == operation
    assert config.signing_key.get_secret_value() not in repr(config)


@pytest.mark.parametrize(
    "changes",
    [
        {"run_id": "../bad"},
        {"actor_id": ""},
        {"tenant_id": ""},
        {"signing_key": SecretStr("")},
    ],
)
async def test_invalid_host_configuration_fails_closed(mock_binding, changes):
    payload = {
        "run_id": "test_01",
        "actor_id": "actor_001",
        "tenant_id": "opsdesk",
        "signing_key": mock_binding.config.signing_key,
        **changes,
    }
    with pytest.raises(ValidationError):
        LaunchConfig(**payload)


async def test_trusted_client_does_not_automatically_retry(mock_binding):
    mock_binding.invoke.side_effect = ServiceError("storage_failure", "safe", retryable=True)
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as sdk:
        client = TrustedClient(sdk, mock_binding.config)
        result = await client.read("get_customer", {"customer_id": "customer_001"})
        assert result.is_error
    assert mock_binding.invoke.call_count == 1


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("create_task", {"title": "Missing customer"}),
        ("create_task", {"customer_id": "customer_001", "title": " "}),
        (
            "create_task",
            {
                "customer_id": "customer_001",
                "title": "No assignment",
                "assigned_actor_id": "support_001",
            },
        ),
        ("update_task", {"task_id": "task_001", "patch": {"status": "resolved"}}),
        (
            "update_task",
            {"task_id": "task_001", "expected_version": "1", "patch": {"status": "resolved"}},
        ),
        ("update_task", {"task_id": "task_001", "expected_version": 1, "patch": {}}),
        ("update_task", {"task_id": "task_001", "expected_version": 1, "patch": {"status": None}}),
        (
            "update_task",
            {"task_id": "task_001", "expected_version": 1, "patch": {"status": "deleted"}},
        ),
    ],
)
async def test_invalid_write_shapes_fail_before_execution(mock_binding, tool, arguments):
    async with Client(create_server("tasks", mock_binding), raise_exceptions=True) as sdk:
        assert (await sdk.call_tool(tool, arguments)).structured_content["error"][
            "code"
        ] == "validation_error"
    mock_binding.invoke.assert_not_called()


async def test_child_environment_does_not_forward_unrelated_secrets(mock_binding, monkeypatch):
    monkeypatch.setenv("OPSDESK_DATABASE_URL", "postgresql+psycopg://localhost/opsdesk_lab_test")
    monkeypatch.setenv("OPENAI_API_KEY", "UNRELATED_SECRET_SENTINEL")
    child = mock_binding.config.child_env()
    assert "OPENAI_API_KEY" not in child
    assert "UNRELATED_SECRET_SENTINEL" not in repr(child)


async def test_database_programming_defect_is_not_retryable_outage(mock_binding):
    from sqlalchemy.exc import ProgrammingError

    mock_binding.invoke.side_effect = ProgrammingError(
        "SENSITIVE_SQL", {}, RuntimeError("PRIVATE_PATH")
    )
    async with Client(create_server("business", mock_binding), raise_exceptions=True) as sdk:
        result = await sdk.call_tool("get_customer", {"customer_id": "customer_001"})
        assert result.structured_content["error"]["code"] == "internal_error"
        assert result.structured_content["error"]["retryable"] is False
        assert "SENSITIVE_SQL" not in result.model_dump_json()
        assert "PRIVATE_PATH" not in result.model_dump_json()
