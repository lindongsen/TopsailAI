"""Shared detached metadata helpers for Agent2LLM run Hook Points. Author: DawsonLin."""

import json
import re
import uuid
from collections.abc import Mapping, Sequence


MAX_PAYLOAD_BYTES = 8192
_OPERATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_POINT_OUTCOMES = {
    "hook__aibase__before__agent_run": "before",
    "hook__aibase__after__agent_run": "success",
    "hook__aibase__error__agent_run": "error",
}


def new_operation_id():
    """Return a bounded opaque identifier for one AgentBase.run invocation."""
    return uuid.uuid4().hex


def _result_kind(result):
    """Return a bounded classification without inspecting result contents."""
    if result is None:
        return "none"
    if isinstance(result, str):
        return "string"
    if isinstance(result, Mapping):
        return "mapping"
    if isinstance(result, Sequence) and not isinstance(result, (bytes, bytearray)):
        return "sequence"
    if isinstance(result, (bool, int, float, complex)):
        return "scalar"
    return "other"


def _safe_token(value, *, fallback="unknown"):
    """Return a bounded class-like token without exposing arbitrary values."""
    if type(value) is not str or not value or len(value) > 128:
        return fallback
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value):
        return fallback
    return value


def build_payload(*, point_name, outcome, operation_id, agent_name, step_call,
                  user_input=None, result=None, error=None,
                  pending_native_tool_responses_cleared=None):
    """Build and validate detached run metadata without business values."""
    expected = _POINT_OUTCOMES.get(point_name)
    if expected != outcome:
        raise ValueError("invalid Agent run Hook point outcome")
    if type(operation_id) is not str or not _OPERATION_ID.fullmatch(operation_id):
        raise ValueError("invalid Agent run Hook operation_id")
    payload = {
        "schema_version": 1,
        "operation_id": operation_id,
        "point_name": point_name,
        "outcome": outcome,
        "agent_layer": "agent2llm_turn",
        "agent_name_present": type(agent_name) is str and bool(agent_name),
        "step_call_type": _safe_token(type(step_call).__name__),
    }
    if outcome == "before":
        payload["user_input_present"] = user_input is not None
    elif outcome == "success":
        if type(pending_native_tool_responses_cleared) is not bool:
            raise ValueError("after Agent run Hook cleanup status is required")
        payload.update(
            result_kind=_result_kind(result),
            result_present=True,
            pending_native_tool_responses_cleared=pending_native_tool_responses_cleared,
        )
    else:
        payload.update(
            error_category=_safe_token(type(error).__name__),
            failed_stage="run_body",
            partial_run_possible=True,
        )
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValueError("Agent run Hook payload exceeds size limit")
    return payload


__all__ = ["MAX_PAYLOAD_BYTES", "build_payload", "new_operation_id"]
