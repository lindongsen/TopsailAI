"""
Human-readable rendering for tool approval requests.

Approval requests are shown to a human who must decide quickly. Rendering the
raw ``tool_args`` dictionary produces a single long line full of ``\\n`` escape
sequences that is hard to scan, and it does not say which rule made the call
require approval.

This module provides:

- :func:`format_tool_args`: pretty-prints tool arguments in a block form where
  multi-line strings keep their real line breaks instead of escape sequences.
- :func:`format_matched`: renders the matched rule as a minimal ``Rule:`` /
  ``Pattern:`` focus block, so the approver knows what triggered the approval.
- :func:`format_approval_request`: assembles the full approval prompt.

Rendering is intentionally dependency-free and defensive: any object can be
passed and the result is always a plain string.
"""

from __future__ import annotations

from typing import Any

from topsailai.utils import env_tool

# Environment variables that bound the rendered output size so that a huge
# tool argument (for example a large file write) cannot flood the terminal.
_ENV_DISPLAY_MAX_LINES = "TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_LINES"
_ENV_DISPLAY_MAX_VALUE_CHARS = "TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_VALUE_CHARS"

DEFAULT_DISPLAY_MAX_LINES = 40
DEFAULT_DISPLAY_MAX_VALUE_CHARS = 2000

# Marker prefixed to every line of a multi-line string value.
_BLOCK_MARKER = "| "
# Indentation used for nested containers.
_INDENT_STEP = "  "


def _get_positive_int_env(name: str, default: int) -> int:
    """Return a positive integer from the environment, falling back to *default*."""
    value = env_tool.get_int(name, default=None)
    if value is None or value <= 0:
        return default
    return value


def get_display_max_lines() -> int:
    """Return the maximum number of rendered lines per value block."""
    return _get_positive_int_env(_ENV_DISPLAY_MAX_LINES, DEFAULT_DISPLAY_MAX_LINES)


def get_display_max_value_chars() -> int:
    """Return the maximum number of characters rendered per scalar value."""
    return _get_positive_int_env(
        _ENV_DISPLAY_MAX_VALUE_CHARS, DEFAULT_DISPLAY_MAX_VALUE_CHARS
    )


def _truncate_text(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars* and annotate how many characters were cut."""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}... (+{omitted} chars)"


def _scalar_to_text(value: Any) -> str:
    """Return a readable single-value representation without escape sequences."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(value)} bytes>"
    return str(value)


def _is_block_value(value: Any) -> bool:
    """
    Return True when *value* must be rendered as a multi-line block.

    Containers always use block form. Strings and bytes that contain a line
    break also use block form so their real line breaks stay readable instead
    of being collapsed into a single line full of ``\\n`` escape sequences.
    """
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return True
    if isinstance(value, str):
        return "\n" in value or "\r" in value
    if isinstance(value, (bytes, bytearray)):
        return b"\n" in value or b"\r" in value
    return False


def _format_inline(value: Any, max_chars: int) -> str:
    """Render a scalar value on a single line."""
    if isinstance(value, str):
        return _truncate_text(value.replace("\r\n", "\n").replace("\n", "\\n"), max_chars)
    return _truncate_text(_scalar_to_text(value), max_chars)


def _append_block_lines(
    lines: list[str],
    text: str,
    indent: str,
    max_lines: int,
    max_chars: int,
) -> None:
    """Append *text* as marker-prefixed lines so real line breaks are preserved."""
    text_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    shown = text_lines[:max_lines]
    for index, line in enumerate(shown):
        # The last line is omitted entirely when it is only a trailing newline,
        # which keeps the block compact for values ending with "\n".
        if index == len(shown) - 1 and line == "" and len(text_lines) > 1:
            break
        lines.append(f"{indent}{_BLOCK_MARKER}{_truncate_text(line, max_chars)}")
    if len(text_lines) > len(shown):
        lines.append(f"{indent}... (+{len(text_lines) - len(shown)} lines)")


def _format_value(value: Any, indent: str, max_lines: int, max_chars: int) -> list[str]:
    """
    Recursively render *value* as indented lines.

    Multi-line strings are rendered as a marker-prefixed block so their content
    is readable literally instead of as ``\\n`` escape sequences.
    """
    if isinstance(value, dict):
        if not value:
            return [f"{indent}{{}}"]
        lines: list[str] = []
        for key, item in value.items():
            key_text = _truncate_text(_scalar_to_text(key), max_chars)
            if not _is_block_value(item):
                lines.append(f"{indent}{key_text}: {_format_inline(item, max_chars)}")
            elif not item:
                lines.append(f"{indent}{key_text}: {_empty_container_text(item)}")
            else:
                lines.append(f"{indent}{key_text}:")
                lines.extend(_format_value(item, f"{indent}{_INDENT_STEP}", max_lines, max_chars))
        return lines

    if isinstance(value, (list, tuple, set, frozenset)):
        if not value:
            return [f"{indent}[]"]
        items = list(value)
        if isinstance(value, (set, frozenset)):
            items = sorted(items, key=_scalar_to_text)
        lines = []
        for item in items:
            if not _is_block_value(item):
                lines.append(f"{indent}- {_format_inline(item, max_chars)}")
            elif not item:
                lines.append(f"{indent}- {_empty_container_text(item)}")
            elif isinstance(item, dict) and len(item) == 1:
                # Compact form for the common single-key dict inside a list.
                key, only_value = next(iter(item.items()))
                key_text = _truncate_text(_scalar_to_text(key), max_chars)
                if not _is_block_value(only_value):
                    lines.append(
                        f"{indent}- {key_text}: {_format_inline(only_value, max_chars)}"
                    )
                    continue
                lines.append(f"{indent}- {key_text}:")
                lines.extend(
                    _format_value(only_value, f"{indent}{_INDENT_STEP}{_INDENT_STEP}", max_lines, max_chars)
                )
            else:
                lines.append(f"{indent}-")
                lines.extend(_format_value(item, f"{indent}{_INDENT_STEP}", max_lines, max_chars))
        return lines

    # Bare multi-line string reached without a key: render as a block.
    lines = []
    _append_block_lines(lines, _scalar_to_text(value), indent, max_lines, max_chars)
    return lines


def _empty_container_text(value: Any) -> str:
    """Return the inline placeholder for an empty container."""
    return "{}" if isinstance(value, dict) else "[]"


def format_tool_args(
    tool_args: Any,
    *,
    max_lines: int | None = None,
    max_value_chars: int | None = None,
) -> str:
    """
    Pretty-print tool arguments for human review.

    Args:
        tool_args: The tool arguments mapping. Non-mapping values are rendered
            defensively as a single value block.
        max_lines: Maximum rendered lines per multi-line value block. Defaults
            to ``TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_LINES``.
        max_value_chars: Maximum characters per rendered scalar. Defaults to
            ``TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_VALUE_CHARS``.

    Returns:
        A multi-line, indented string. Returns an empty string when there are
        no arguments.
    """
    if max_lines is None:
        max_lines = get_display_max_lines()
    if max_value_chars is None:
        max_value_chars = get_display_max_value_chars()

    if tool_args is None:
        return ""
    if isinstance(tool_args, dict) and not tool_args:
        return ""

    if not isinstance(tool_args, dict):
        lines = _format_value(tool_args, "", max_lines, max_value_chars)
        return "\n".join(lines)

    lines = _format_value(tool_args, "", max_lines, max_value_chars)
    return "\n".join(lines)


def _rule_field(rule: Any, key: str, default: Any = "") -> Any:
    """
    Read a rule field from either a mapping or an object.

    Rules normally come from JSON, so a plain ``dict`` must render as well as
    the ``ApprovalRule`` dataclass does.
    """
    if isinstance(rule, dict):
        value = rule.get(key, default)
    else:
        value = getattr(rule, key, default)
    return default if value is None else value


def format_matched(rule: Any) -> str:
    """
    Render the matched rule as a minimal two-line focus block.

    Only the rule name and its tool-name pattern are shown: they are enough for
    the approver to know which configuration made this call require approval.
    Parameter conditions are intentionally not rendered here because the full
    arguments are already displayed below in the approval request.

    Args:
        rule: The matched ``ApprovalRule`` (or any mapping/object exposing
            ``name`` and ``match`` fields). ``None`` renders an empty string so
            the caller can omit the block entirely.

    Returns:
        ``"Rule: ...\nPattern: ..."`` or an empty string when there is no rule.
    """
    if rule is None:
        return ""

    name = _rule_field(rule, "name", "") or "<unnamed>"
    pattern = _rule_field(rule, "match", "")

    return "\n".join(
        [
            f"Rule: {name}",
            f"Pattern: {pattern}",
        ]
    )


def _indent_block(text: str, indent: str) -> str:
    """Indent every non-empty line of *text* with *indent*."""
    if not text:
        return ""
    return "\n".join(
        f"{indent}{line}" if line else line for line in text.split("\n")
    )


def format_approval_request(instance: Any) -> str:
    """
    Build the full human-readable approval request text for *instance*.

    The returned string ends with the input prompt suffix so it can be passed
    directly to an input function.

    Args:
        instance: A ``ToolApprovalInstance`` (or any object exposing
            ``id``, ``tool_name``, ``tool_args`` and ``timeout``).
    """
    instance_id = getattr(instance, "id", "") or "<unknown>"
    tool_name = getattr(instance, "tool_name", "") or "<unknown>"
    timeout = getattr(instance, "timeout", None)

    max_lines = get_display_max_lines()
    max_value_chars = get_display_max_value_chars()

    parts: list[str] = [f"[APPROVAL REQUEST] {instance_id}"]

    # The matched rule is shown first so the approver immediately sees which
    # rule made this call require approval. When no rule object is available,
    # fall back to a plain rule name so the reason stays visible.
    rule = getattr(instance, "matched_rule", None)
    matched = format_matched(rule)
    if matched:
        parts.append(_indent_block(matched, "  "))
    elif rule is None:
        rule_name = getattr(instance, "rule_name", None)
        if rule_name:
            parts.append(f"  Rule   : {rule_name}")

    parts.append(f"  Tool   : {tool_name}")
    if timeout is not None:
        parts.append(f"  Timeout: {timeout}s")

    policy = getattr(instance, "policy", None)
    if policy:
        parts.append(f"  Policy : {policy}")

    # Full arguments section: pretty printed, real line breaks preserved.
    parts.append("  Args:")
    args_text = format_tool_args(
        getattr(instance, "tool_args", None),
        max_lines=max_lines,
        max_value_chars=max_value_chars,
    )
    parts.append(_indent_block(args_text, "    ") if args_text else "    (none)")

    parts.append("")
    parts.append("  Type 'approve'(yes) or 'deny'(no): ")
    return "\n".join(parts)
