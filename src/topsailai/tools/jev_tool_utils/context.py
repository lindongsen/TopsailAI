"""Agent2LLM context export for the JEV decision tool."""

import copy
import json
import math
import re
from typing import Any

from topsailai.utils.message_tool import normalize_tool_calls

_SENSITIVE_KEY = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?token|password|secret)", re.IGNORECASE
)
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s\"']+")


class JevContextError(ValueError):
    """Identify unavailable runtime context."""


def _mapping(value: Any) -> dict | None:
    """Convert a runtime object to a detached plain mapping."""
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return copy.deepcopy(parsed) if isinstance(parsed, dict) else None
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                parsed = method()
            except Exception:
                continue
            if isinstance(parsed, dict):
                return copy.deepcopy(parsed)
    result = {}
    for field in ("role", "content", "tool_calls", "tool_call_id", "name"):
        item = getattr(value, field, None)
        if item is not None:
            result[field] = copy.deepcopy(item)
    return result or None


def _redact(value: Any, api_key: str, key: str = "") -> Any:
    """Redact secrets and normalize runtime values to JSON-safe content."""
    if _SENSITIVE_KEY.search(str(key)):
        return "***"
    if isinstance(value, dict):
        return {
            str(item_key): _redact(item, api_key, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, api_key) for item in value]
    if isinstance(value, str):
        result = value.replace(api_key, "***") if api_key else value
        return _BEARER.sub(r"\1***", result)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[unsupported-non-finite-number]"
    return f"[unsupported-{type(value).__name__}]"


def _normalize_tool_call(tool_call: dict) -> dict:
    """Keep only JEV-relevant tool-call attribution fields."""
    function = tool_call.get("function") or {}
    return {
        "id": str(tool_call.get("id", "")),
        "name": str(function.get("name", "")),
        "arguments": function.get("arguments", ""),
    }


def _ordinary_message(message: dict, api_key: str) -> dict:
    """Normalize one ordinary user or assistant message."""
    return _redact(
        {"role": message["role"], "content": message.get("content", "")}, api_key
    )


def _tool_group(messages: list[dict], index: int, api_key: str):
    """Return one complete assistant/tool group and its final source index."""
    owner = messages[index]
    normalized_calls, malformed = normalize_tool_calls(owner.get("tool_calls"))
    if malformed or not normalized_calls:
        return None, index
    declared_ids = [call["id"] for call in normalized_calls]
    replies = []
    cursor = index + 1
    while cursor < len(messages) and messages[cursor].get("role") == "tool":
        reply = messages[cursor]
        if reply.get("tool_call_id") in declared_ids:
            replies.append(reply)
        cursor += 1
    if {reply.get("tool_call_id") for reply in replies} != set(declared_ids):
        return None, cursor - 1
    exported_owner = {
        "role": "assistant",
        "content": owner.get("content", ""),
        "tool_calls": [_normalize_tool_call(call) for call in normalized_calls],
    }
    exported_replies = [
        {
            "role": "tool",
            "tool_call_id": reply.get("tool_call_id"),
            "name": reply.get("name", ""),
            "content": reply.get("content", ""),
        }
        for reply in replies
    ]
    return [_redact(exported_owner, api_key), *[_redact(reply, api_key) for reply in exported_replies]], cursor - 1


def _build_units(messages: list[dict], api_key: str) -> list[list[dict]]:
    """Build pair-atomic export units while omitting unsupported messages."""
    units = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message.get("role")
        if role == "system" or role == "tool":
            index += 1
            continue
        if role == "assistant" and message.get("tool_calls"):
            group, final_index = _tool_group(messages, index, api_key)
            if group:
                units.append(group)
            index = final_index + 1
            continue
        if role in {"user", "assistant"}:
            units.append([_ordinary_message(message, api_key)])
        index += 1
    return units


def _serialized_length(units: list[list[dict]]) -> int:
    """Return the deterministic serialized state length."""
    messages = [message for unit in units for message in unit]
    return len(json.dumps({"agent2llm_messages": messages}, ensure_ascii=False, separators=(",", ":")))


def _truncate_value(value: Any, allowance: int) -> Any:
    """Return a deterministic bounded representation of one content value."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= allowance:
        return value
    if allowance <= 24:
        return "[truncated]"
    keep = max((allowance - 15) // 2, 1)
    return f"{text[:keep]}...[truncated]...{text[-keep:]}"


def _truncate_newest_unit(unit: list[dict], max_chars: int) -> list[dict]:
    """Shrink content fields while retaining tool-pair metadata."""
    result = copy.deepcopy(unit)
    fields = [message for message in result if "content" in message]
    allowance = max(max_chars // max(len(fields), 1) // 2, 16)
    for message in fields:
        message["content"] = _truncate_value(message.get("content", ""), allowance)
        message["truncated"] = True
    for message in result:
        for tool_call in message.get("tool_calls", []):
            tool_call["arguments"] = _truncate_value(tool_call.get("arguments", ""), allowance)
    while _serialized_length([result]) > max_chars and allowance > 16:
        allowance = max(allowance // 2, 16)
        for message in fields:
            message["content"] = _truncate_value(message.get("content", ""), allowance)
    return result


def build_state(agent: Any, api_key: str, max_messages: int, max_chars: int) -> dict:
    """Build a bounded non-mutating Agent2LLM state envelope."""
    source = getattr(agent, "messages", None) if agent is not None else None
    if not isinstance(source, (list, tuple)) or not source:
        raise JevContextError("no_runtime_context")
    normalized = []
    for message in source:
        mapped = _mapping(message)
        if mapped:
            normalized.append(mapped)
    units = _build_units(normalized, api_key)
    while units and sum(len(unit) for unit in units) > max_messages:
        units.pop(0)
    while len(units) > 1 and _serialized_length(units) > max_chars:
        units.pop(0)
    if units and _serialized_length(units) > max_chars:
        units = [_truncate_newest_unit(units[-1], max_chars)]
    if units and _serialized_length(units) > max_chars:
        raise JevContextError("context_limit_too_small")
    messages = [message for unit in units for message in unit]
    if not messages:
        raise JevContextError("no_eligible_runtime_context")
    return {"agent2llm_messages": messages}
