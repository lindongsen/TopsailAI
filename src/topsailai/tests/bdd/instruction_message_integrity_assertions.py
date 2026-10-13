"""Independent parsers and declarative message-integrity assertions."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_agent_messages(output: str) -> list[dict[str, Any]]:
    """Parse the JSON payload and exact count footer from ``/agent.messages``."""
    text = output.lstrip()
    decoder = json.JSONDecoder()
    try:
        payload, end = decoder.raw_decode(text)
    except json.JSONDecodeError as error:
        raise AssertionError(f"invalid agent.messages report: {output!r}") from error
    suffix = text[end:]
    match = re.fullmatch(r"\s*---\s*\n\s*TotalCount: (\d+)\s*", suffix)
    if not match or not isinstance(payload, list):
        raise AssertionError(f"invalid agent.messages report: {output!r}")
    if int(match.group(1)) != len(payload):
        raise AssertionError("agent.messages footer count does not match payload")
    return payload


def parse_history_roles_and_content(output: str) -> list[tuple[str, str]]:
    """Parse ordered role/content blocks from human-readable ``/ctx.history``."""
    headers = list(re.finditer(
        r"#(\d+) - Role: ([A-Z]+) - Words: \d+ - Tokens: \d+(?: - [^\n]+)?\n={80}\n",
        output,
    ))
    result = []
    for index, header in enumerate(headers):
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(output)
        result.append((header.group(2).lower(), output[start:end].strip()))
    if [int(item.group(1)) for item in headers] != list(range(1, len(headers) + 1)):
        raise AssertionError("history message numbering is not sequential")
    if not headers and "Show history messages" not in output:
        raise AssertionError("history report has no recognizable header")
    return result


def _message_content(message: dict[str, Any]) -> str:
    """Return message text without changing its semantic ordering."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def assert_message_manifest(
    messages: list[dict[str, Any]], manifest: list[dict[str, Any]]
) -> None:
    """Assert exact message count, roles, marker order, and marker cardinality."""
    if len(messages) != len(manifest):
        raise AssertionError(f"message count {len(messages)} != {len(manifest)}")
    for index, (message, expected) in enumerate(zip(messages, manifest)):
        role = message.get("role")
        if role != expected["role"]:
            raise AssertionError(f"message {index} role {role!r} != {expected['role']!r}")
        content = _message_content(message)
        expected_markers = expected.get("markers", [])
        all_markers = expected.get("all_markers", expected_markers)
        positions = []
        for marker in all_markers:
            count = content.count(marker)
            wanted = 1 if marker in expected_markers else 0
            if count != wanted:
                raise AssertionError(
                    f"message {index} marker {marker!r} count {count} != {wanted}"
                )
            if wanted:
                positions.append((content.index(marker), marker))
        if [marker for _, marker in sorted(positions)] != expected_markers:
            raise AssertionError(f"message {index} marker order is incorrect")


def ordered_markers(messages: list[dict[str, Any]], markers: list[str]) -> list[str]:
    """Return every marker occurrence in actual message and content order."""
    found: list[tuple[int, int, str]] = []
    for message_index, message in enumerate(messages):
        content = _message_content(message)
        for marker in markers:
            start = 0
            while True:
                position = content.find(marker, start)
                if position < 0:
                    break
                found.append((message_index, position, marker))
                start = position + len(marker)
    return [marker for _, _, marker in sorted(found)]


def _native_pair(messages: list[dict[str, Any]], *, task_marker: str, tool_name: str, call_id: str, argument: dict[str, Any], result_marker: str, result_content: str) -> None:
    """Validate the task, declaration, and matching tool-result portion."""
    if len(messages) < 3:
        raise AssertionError("native group is incomplete")
    if messages[0].get("role") != "user" or task_marker not in _message_content(messages[0]):
        raise AssertionError("native task is not first")
    declaration, result = messages[1], messages[2]
    calls = declaration.get("tool_calls") if declaration.get("role") == "assistant" else None
    if not isinstance(calls, list) or len(calls) != 1:
        raise AssertionError("native declaration must contain one tool call")
    call = calls[0]
    if isinstance(call, str):
        id_match = re.search(r"id='([^']+)'", call)
        type_match = re.search(r"type='([^']+)'", call)
        function_match = re.search(r"arguments='(.*)', name='([^']+)'", call)
        if id_match and type_match and function_match:
            call = {"id": id_match.group(1), "type": type_match.group(1), "function": {"arguments": function_match.group(1), "name": function_match.group(2)}}
    def field(value, name):
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    function = field(call, "function")
    if field(call, "id") != call_id or field(call, "type") != "function":
        raise AssertionError("native call identity is incorrect")
    if field(function, "name") != tool_name:
        raise AssertionError("native function name is incorrect")
    try:
        actual_arguments = json.loads(field(function, "arguments") or "")
    except (TypeError, json.JSONDecodeError) as error:
        raise AssertionError("native arguments are not JSON") from error
    if actual_arguments != argument:
        raise AssertionError("native arguments are incorrect")
    if result.get("role") != "tool" or result.get("tool_call_id") != call_id:
        raise AssertionError("native result does not match declaration")
    if _message_content(result) != result_content:
        raise AssertionError(f"native result serialization is incorrect: {_message_content(result)!r}")
    if _message_content(result).count(result_marker) != 1:
        raise AssertionError("native result marker cardinality is incorrect")


def assert_native_tool_group(messages: list[dict[str, Any]], *, task_marker: str, tool_name: str, call_id: str, argument: dict[str, Any], result_marker: str, result_content: str | None = None, final_marker: str | None = None) -> None:
    """Validate one task, native declaration, result, and final answer."""
    if len(messages) != 4:
        raise AssertionError(f"native group length {len(messages)} != 4")
    expected_result = result_content if result_content is not None else result_marker
    _native_pair(messages[:3], task_marker=task_marker, tool_name=tool_name, call_id=call_id, argument=argument, result_marker=result_marker, result_content=expected_result)
    if messages[3].get("role") != "assistant":
        raise AssertionError("native final answer is not last")
    final_content = _message_content(messages[3])
    if call_id in final_content:
        raise AssertionError("native call id leaked into final answer")
    if final_marker is not None and final_content.count(final_marker) != 1:
        raise AssertionError("native final marker cardinality is incorrect")
    for message in messages[:3]:
        content = _message_content(message)
        if final_marker is not None and final_marker in content:
            raise AssertionError("native final marker leaked before final answer")



def assert_system_context(
    messages: list[dict[str, Any]],
    forbidden_markers: list[str],
    *,
    expected_markers: list[str] | None = None,
    expected_count: int | None = None,
) -> None:
    """Require leading, meaningful system context with fixture-controlled content."""
    system_messages = [message for message in messages if message.get("role") == "system"]
    if not system_messages:
        raise AssertionError("request has no system context")
    first_non_system = next(
        (index for index, message in enumerate(messages) if message.get("role") != "system"),
        len(messages),
    )
    if any(message.get("role") == "system" for message in messages[first_non_system:]):
        raise AssertionError("system context is not leading")
    if any(not _message_content(message).strip() for message in system_messages):
        raise AssertionError("system context is empty")
    if expected_count is not None and len(system_messages) != expected_count:
        raise AssertionError(
            f"system message count {len(system_messages)} != {expected_count}"
        )
    if expected_markers is not None:
        actual_markers = [
            marker
            for message in system_messages
            for marker in expected_markers
            for _ in range(_message_content(message).count(marker))
        ]
        if actual_markers != expected_markers:
            raise AssertionError(
                f"system fixture markers {actual_markers!r} != {expected_markers!r}"
            )
    for message in system_messages:
        content = _message_content(message)
        for marker in forbidden_markers:
            if marker in content and (expected_markers is None or marker not in expected_markers):
                raise AssertionError(f"conversation marker leaked into system context: {marker}")

def assert_native_wire_group(messages: list[dict[str, Any]], *, task_marker: str, tool_name: str, call_id: str, argument: dict[str, Any], result_marker: str, result_content: str | None = None) -> None:
    """Validate one task, declaration, and result before the future answer."""
    if len(messages) != 3:
        raise AssertionError(f"native wire group length {len(messages)} != 3")
    _native_pair(messages, task_marker=task_marker, tool_name=tool_name, call_id=call_id, argument=argument, result_marker=result_marker, result_content=result_content if result_content is not None else result_marker)
