"""Bounded capture/redaction shared by graph state, journal and operation intents."""

import json
import os
import re
from datetime import datetime

from pydantic import Field, field_validator
from sqlalchemy.engine import make_url

from agent_reliability_lab.benchmarks.scenario import Contract

EVENTS = frozenset(
    {
        "run_started",
        "run_resumed",
        "run_interrupted",
        "model_request",
        "model_response",
        "model_failed",
        "tool_call_proposed",
        "tool_call_rejected",
        "tool_call_started",
        "tool_call_succeeded",
        "tool_call_failed",
        "retry_scheduled",
        "budget_exhausted",
        "run_completed",
        "run_failed",
        "injection_trigger",
        "injection_activated",
        "injection_not_applied",
        "injection_observed",
        "injection_model_exposure",
        "defense_block",
    }
)


class JournalEvent(Contract):
    execution_id: str
    sequence: int = Field(ge=1)
    event_type: str
    timestamp: datetime
    elapsed_ms: float = Field(ge=0)
    payload: dict

    @field_validator("event_type")
    @classmethod
    def known_event(cls, value: str) -> str:
        if value not in EVENTS:
            raise ValueError("unknown journal event type")
        return value


class Redactor:
    def __init__(self, additional: tuple[str, ...] = ()):
        values = [
            value
            for name, value in os.environ.items()
            if any(
                word in name.upper()
                for word in ("KEY", "TOKEN", "PASSWORD", "SECRET", "DATABASE_URL")
            )
            and len(value) >= 8
        ]
        url = os.environ.get("OPSDESK_DATABASE_URL")
        if url:
            password = make_url(url).password
            if password:
                values.append(password)
        self.values = sorted(set([*values, *additional]), key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self.values:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?:sk-[A-Za-z0-9_-]{12,}|github_pat_[A-Za-z0-9_]+)", "[REDACTED]", value)
        value = re.sub(
            r"(?:postgresql(?:\+psycopg)?|https?)://[^\s\"<>]+:[^\s\"<>]+@[^\s\"<>]+",
            "[REDACTED_URL]",
            value,
        )
        return value

    def clean(self, value):
        if isinstance(value, str):
            safe = self.text(value)
            # Tool arguments arrive as JSON strings inside provider messages.
            try:
                nested = json.loads(safe)
            except (ValueError, TypeError):
                return safe
            if isinstance(nested, (dict, list)):
                cleaned = self.clean(nested)
                return json.dumps(cleaned, ensure_ascii=False) if cleaned != nested else safe
            return safe
        if isinstance(value, list):
            return [self.clean(item) for item in value]
        if isinstance(value, dict):
            return {
                self.text(key): "[REDACTED]"
                if any(
                    word in key.lower()
                    for word in ("password", "api_key", "signing_key", "authorization", "signature")
                )
                else self.clean(item)
                for key, item in value.items()
            }
        return value

    def capture(self, value, limit=2048):
        cleaned = self.clean(value)
        encoded = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode()) <= limit:
            return cleaned
        return {"preview": encoded[: limit // 4], "truncated": True}
