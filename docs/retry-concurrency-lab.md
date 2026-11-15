# Retry and concurrency lab

Run the PostgreSQL tests only on a fresh, owned database.

```text
uv run --locked --extra stack opsdesk-lab test
```

The same-key receipt lookup runs inside the write transaction. Its scope includes
the tenant, actor, tool and key. The validated argument hash is checked before the
original receipt is returned. One sandbox identity lock serializes task writes.
Notification writes use a tenant actor row lock and a unique sandbox-incarnation,
actor and operation identity.

| Fault or control | Production-path regression |
|---|---|
| Single write, matching replay, conflicting intent | `test_idempotent_create_update_and_conflicting_reuse` |
| Two concurrent deliveries through MCP | `test_concurrent_retry_safety_over_protocol` |
| Six deliveries while the first transaction is open | `test_retry_waits_for_uncommitted_receipt_then_reuses_it` |
| Process dies before the transaction commits | `test_process_death_before_commit_allows_one_fresh_retry` |
| Process dies after commit and resumes on a new host | `test_hard_process_restart_after_committed_write`, `test_v170_stdio_process_restart_keeps_original_intent_and_commit` |
| Same key across authorized tenants, then authorization revoked | `test_same_key_in_distinct_tenants_and_denied_replay` |
| Lost MCP acknowledgment through memory and stdio | `test_real_agent_retries_and_later_evidence_appends` |
| Matching and conflicting signed intent after model context changes | `test_changed_model_input_does_not_change_signed_write_intent` |
| Unsigned, wrong-role and conflicting signed requests | `test_mcp_signed_retry_and_authorization` |
| Concurrent downstream replay and payload conflict | `test_duplicate_provider_requests_and_conflicting_payload` |

A physical attempt is a dispatch record. A verified write needs a matching
committed receipt and effect. The demo verifies receipt reuse using a controlled
response loss and the matching committed intent/outbox pair. Existing historical
receipts do not identify which physical attempt originally committed.
