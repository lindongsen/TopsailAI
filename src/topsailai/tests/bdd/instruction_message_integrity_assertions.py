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
