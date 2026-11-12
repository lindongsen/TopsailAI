"""LLM request failure report declaration. Author: DawsonLin."""

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

NAME = "hook__aibase__after__llm_request_failures"
# One request is bounded by the retry loop (18 attempts per cycle, at most 8
# cycles). The cap only protects against a future unbounded loop, and it also
# bounds the report payload.
MAX_FAILURES = 200
# Keep one failure line readable; the complete error text stays in the attempt log.
FAILURE_MESSAGE_MAX_CHARS = 200
# A truncated message keeps its ellipsis suffix.
MESSAGE_MAX_CHARS = FAILURE_MESSAGE_MAX_CHARS + 3

FAILURE_PROPERTIES = {
    "attempt": {"type": "integer"},
    "error": {"type": "string"},
    "duration_sec": {"type": "number"},
    "message": {"type": "string"},
}

PROPERTIES = {
    "schema_version": {"type": "integer"},
    "operation_id": {"type": "string"},
    "outcome": {"type": "string"},
    "failed_attempts": {"type": "integer"},
    "last_failed_attempt": {"type": "integer"},
    "elapsed_sec": {"type": "number"},
    "dropped_failures": {"type": "integer"},
    "failures": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": FAILURE_PROPERTIES,
            "required": list(FAILURE_PROPERTIES),
        },
        "max_items": MAX_FAILURES,
    },
}

POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema={
            "type": "object", "properties": PROPERTIES,
            "required": list(PROPERTIES),
        },
        payload_limit_bytes=65_536,
    ),
    phase="success", mode="sync", owner="ai_base.llm_request_failures",
    failure_policy="report", latency_budget_ms=1_000,
)

__all__ = [
    "NAME", "POINT", "MAX_FAILURES", "FAILURE_MESSAGE_MAX_CHARS",
    "MESSAGE_MAX_CHARS",
]
