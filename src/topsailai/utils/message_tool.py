"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-16
Purpose: Semantic message comparison helpers used across layers.
"""

from topsailai.ai_base.constants import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
)
from topsailai.utils import json_tool


def _tool_call_mapping(value):
    """Return a plain mapping for one tool call without stringifying it."""
    if isinstance(value, dict):
        return value
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if not callable(method):
            continue
        try:
            dumped = method()
        except Exception:
            continue
        if isinstance(dumped, dict):
            return dumped
    return None


def normalize_tool_calls(value):
    """Normalize valid tool calls to JSON-compatible mappings.

    JSON strings are accepted only when they decode to a valid tool-call list.
    SDK repr strings and other malformed values are rejected rather than
    reconstructed heuristically.

    Args:
        value: A tool_calls value from a runtime or persisted message.

    Returns:
        tuple: ``(normalized_value, malformed_type)``. ``malformed_type`` is
        empty when the value is valid. Valid plain dictionaries are preserved.
    """
    original_type = type(value).__name__
    if isinstance(value, str):
        try:
            value = json_tool.json_load(value)
        except Exception:
            return None, original_type
    if not isinstance(value, list):
        return None, original_type

    normalized = []
    for item in value:
        item_type = type(item).__name__
        mapping = _tool_call_mapping(item)
        if not mapping:
            return None, item_type
        function = _tool_call_mapping(mapping.get("function"))
        if not mapping.get("id") or not mapping.get("type") or function is None:
            return None, item_type
        if function is not mapping.get("function"):
            mapping = dict(mapping)
            mapping["function"] = function
        normalized.append(mapping)
    return normalized, ""


def normalize_message_tool_calls(messages: list, logger=None) -> list:
    """Normalize assistant tool calls and strip malformed persisted values.

    The input list is mutated intentionally at serialization/request boundaries.
    Warnings include only the message index and malformed type.
    """
    if not messages:
        return messages
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict) or msg.get("role") != ROLE_ASSISTANT:
            continue
        if "tool_calls" not in msg or msg.get("tool_calls") is None:
            continue
        normalized, malformed_type = normalize_tool_calls(msg.get("tool_calls"))
        if malformed_type:
            msg.pop("tool_calls", None)
            if logger:
                logger.warning(
                    "strip malformed assistant tool_calls: index=%s type=%s",
                    index,
                    malformed_type,
                )
            continue
        msg["tool_calls"] = normalized
    return messages


def _normalize_message_value(value):
    """
    Recursively normalize a message value so JSON-string payloads are parsed
    before comparison.

    - Strings that are valid JSON are parsed and the result is normalized
      recursively. This handles message ``content`` fields that are stored
      as serialized JSON objects/lists.
    - Dict values and list items are normalized recursively so nested
      JSON strings are also unpacked.
    - Other values are returned unchanged.

    Note: scalar JSON strings such as "123", "true", "null" or '"hello"'
    are parsed to their Python values (int, bool, None, str). Callers that
    need to distinguish a JSON number string from a plain string should
    compare the original values before normalization.

    Args:
        value: A message value (dict, list, str, or other).

    Returns:
        The normalized value.
    """
    if isinstance(value, str):
        try:
            parsed = json_tool.json_load(value)
        except Exception:
            return value
        return _normalize_message_value(parsed)
    if isinstance(value, dict):
        return {
            k: _normalize_message_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_message_value(v)
            for v in value
        ]
    return value


def message_equal(a, b) -> bool:
    """
    Compare two messages for semantic equality.

    Messages may be dict instances, JSON strings, or plain strings. Two
    messages are considered equal when their content is the same, even if
    they are different object instances, one is a dict and the other is
    its JSON serialization, or nested ``content`` fields mix serialized
    JSON strings with parsed dict/list values.

    Comparison order:
    1. Same object identity -> equal.
    2. Direct equality (``a == b``) -> equal if True. This covers plain
       strings, numbers, and value equality for list/dict.
    3. Recursively normalize JSON-string payloads in both operands and
       compare the normalized values with ``==``.

    Args:
        a: First message (dict, list, str, or other).
        b: Second message (dict, list, str, or other).

    Returns:
        bool: True if the messages are semantically equal, False otherwise.
    """
    if a is b:
        return True

    # Direct equality covers strings, numbers, list/dict value equality.
    try:
        if a == b:
            return True
    except Exception:
        pass

    # Normalize JSON-string payloads recursively and compare again.
    # This handles cases such as:
    #   {"content": '{"step_name": "observation"}'}
    # vs
    #   {"content": {"step_name": "observation"}}
    try:
        a_normalized = _normalize_message_value(a)
        b_normalized = _normalize_message_value(b)
        if a_normalized == b_normalized:
            return True
    except Exception:
        pass

    return False


def message_in_list(msg, msg_list: list) -> bool:
    """
    Check whether a semantically equal message already exists in a list.

    Uses :func:`message_equal` so that dict/list content is compared by
    value and JSON-string representations are normalized before comparing.
    An identity check (``is``) is performed first because most messages are
    not modified during summarization.

    Args:
        msg: The message to search for.
        msg_list (list): The list of messages to search in.

    Returns:
        bool: True if an equal message is found, False otherwise.
    """
    # Fast path: identity check first.
    for m in msg_list:
        if m is msg:
            return True
    # Fallback: semantic equality.
    for m in msg_list:
        if message_equal(m, msg):
            return True
    return False


def message_index_in_list(msg, msg_list: list) -> int:
    """
    Find the index of the first message in ``msg_list`` that is semantically
    equal to ``msg``.

    Uses :func:`message_equal` for content-based matching. An identity check
    (``is``) is performed first because most messages are not modified during
    summarization.

    Args:
        msg: The message to search for.
        msg_list (list): The list of messages to search in.

    Returns:
        int: The zero-based index of the matching message, or -1 if not found.
    """
    # Fast path: identity check first.
    for i, m in enumerate(msg_list):
        if m is msg:
            return i
    # Fallback: semantic equality.
    for i, m in enumerate(msg_list):
        if message_equal(m, msg):
            return i
    return -1


def extract_tool_call_ids(msg) -> list:
    """
    Collect ``tool_calls`` ids carried by a message.

    Supports both message shapes produced at runtime:

    - ``dict`` messages built by ``PromptBase.add_assistant_message``.
    - Objects exposing a ``tool_calls`` attribute.

    Each ``tool_calls`` entry may itself be a plain ``dict`` or an OpenAI SDK
    pydantic object, so ids are read defensively.

    Args:
        msg: A message dict or object.

    Returns:
        list: Non-empty ids in declaration order. Empty list when absent.
    """
    tool_calls = None
    if isinstance(msg, dict):
        tool_calls = msg.get("tool_calls")
    else:
        tool_calls = getattr(msg, "tool_calls", None)

    if not tool_calls:
        return []

    ids = []
    for tc in tool_calls:
        tc_id = None
        if isinstance(tc, dict):
            tc_id = tc.get("id")
        else:
            tc_id = getattr(tc, "id", None)
            if tc_id is None and callable(getattr(tc, "model_dump", None)):
                tc_id = tc.model_dump().get("id")
        if tc_id:
            ids.append(tc_id)
    return ids


def drop_orphaned_tool_messages(messages: list, logger=None) -> list:
    """
    Drop ``role="tool"`` messages without a preceding assistant ``tool_calls`` id.

    Native tool calls require an intact ``tool_calls`` / ``tool_call_id``
    pairing. Context summarization, session truncation and index-based message
    pruning can all keep a tool observation while its owning assistant message
    is removed, which makes providers reject the whole request with errors such
    as ``No tool call found for function call output with call_id ...``. Such a
    broken list is sticky: every retry and every later turn keeps failing.

    This helper is intentionally pure: it never reads environment variables and
    never mutates the input list, so callers own the enable switch and tests
    stay isolated.

    Args:
        messages (list): Messages to sanitize.
        logger: Optional logger used to record every dropped message.

    Returns:
        list: New list with orphaned tool messages removed. The original list
        object is never returned nor modified.
    """
    if not messages:
        return []

    valid_tool_call_ids = set()
    cleaned = []
    for index, msg in enumerate(messages):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role == ROLE_ASSISTANT:
            valid_tool_call_ids.update(extract_tool_call_ids(msg))
        elif role == ROLE_TOOL:
            tool_call_id = (
                msg.get("tool_call_id") if isinstance(msg, dict)
                else getattr(msg, "tool_call_id", None)
            )
            if tool_call_id and tool_call_id not in valid_tool_call_ids:
                if logger:
                    tool_name = (
                        msg.get("name") if isinstance(msg, dict)
                        else getattr(msg, "name", None)
                    )
                    logger.warning(
                        "drop orphaned tool message: index=%s tool_call_id=%s name=%s",
                        index,
                        tool_call_id,
                        tool_name or "",
                    )
                continue
        cleaned.append(msg)
    return cleaned


def _message_view(msg):
    """Return a dict-like view of a message stored as dict, object or JSON string.

    Context layers may hold messages either as ``dict`` instances, as objects
    exposing ``role``/``tool_calls``/``tool_call_id`` attributes, or as JSON
    strings persisted by the session layer. Pairing checks need one accessor
    that tolerates all three shapes.

    Args:
        msg: A message dict, object, or JSON string.

    Returns:
        dict | None: Mapping with the pairing fields when they can be read,
        otherwise ``None``.
    """
    if isinstance(msg, dict):
        return msg
    if isinstance(msg, str):
        parsed = json_tool.safe_json_load(msg)
        return parsed if isinstance(parsed, dict) else None

    view = {}
    for field in ("role", "tool_calls", "tool_call_id"):
        value = getattr(msg, field, None)
        if value is not None:
            view[field] = value
    return view


def _tool_call_owner_index(messages: list, tool_call_id, end_index: int, floor: int):
    """Find the latest assistant message before ``end_index`` declaring ``tool_call_id``.

    Args:
        messages (list): Messages in chronological order.
        tool_call_id: The id whose owning assistant message is searched.
        end_index (int): Exclusive upper bound of the search.
        floor (int): Inclusive lower bound of the search.

    Returns:
        int | None: The owner index, or ``None`` when it is absent or below
        ``floor`` (i.e. outside the region the caller allows to preserve).
    """
    for index in range(end_index - 1, floor - 1, -1):
        msg = _message_view(messages[index])
        if not msg or msg.get("role") != ROLE_ASSISTANT:
            continue
        if tool_call_id in extract_tool_call_ids(msg):
            return index
    return None


def _earliest_missing_owner_index(messages: list, start: int, floor: int):
    """Find the earliest owner that a tool message inside ``[start, len)`` needs.

    Only owners located in ``[floor, start)`` are considered: an owner already
    inside the window needs no action, and an owner below ``floor`` cannot be
    preserved without crossing into the summarized region.

    Args:
        messages (list): Messages in chronological order.
        start (int): First index of the preserved window.
        floor (int): Earliest index the window is allowed to reach.

    Returns:
        int | None: The earliest owner index, or ``None`` when every tool
        message in the window is already paired inside it.
    """
    earliest = None
    for index in range(start, len(messages)):
        msg = _message_view(messages[index])
        if not msg or msg.get("role") != ROLE_TOOL:
            continue
        tool_call_id = msg.get("tool_call_id")
        if not tool_call_id:
            continue
        owner = _tool_call_owner_index(messages, tool_call_id, start, floor)
        if owner is None:
            continue
        if earliest is None or owner < earliest:
            earliest = owner
    return earliest


def expand_tail_start_for_tool_pairing(
    messages: list,
    start_index: int,
    min_start: int = 0,
) -> int:
    """Expand a count-based tail window so it never starts with an orphan tool.

    Summarization selects the preserved tail by message count, so the window
    can begin on a ``role="tool"`` observation while the assistant message
    carrying its ``tool_calls`` id falls into the summarized middle. Providers
    then reject the rebuilt context with ``No tool call found for function call
    output with call_id ...``, and the failure is sticky because the broken
    list is resent on every retry and every later turn.

    This helper moves the window start back to the earliest owning assistant
    message so the preserved window is pair-atomic. It is bounded by
    ``min_start`` so the window can never cross into the summarized region or
    swallow the whole list, and it leaves the start untouched when the owner
    lies below that bound (the request-boundary sanitizer drops such an
    orphan). Extending to the earliest owner also covers every owner located
    between it and the original start, so a single pass is sufficient.

    Args:
        messages (list): Messages in chronological order.
        start_index (int): Original count-based window start.
        min_start (int): Earliest index the window may reach.

    Returns:
        int: The adjusted window start, always within ``[0, len(messages)]``.
    """
    total = len(messages) if messages else 0
    if total == 0:
        return max(start_index, 0)

    start = min(max(start_index, 0), total)
    floor = min(max(min_start, 0), total)
    if start <= floor:
        return start

    owner = _earliest_missing_owner_index(messages, start, floor)
    return start if owner is None else owner


def _sort_indexes(indexes) -> list:
    """Sort indexes without failing on mixed or non-numeric values.

    Delete indexes can originate from LLM tool arguments, so a non-integer
    value must not turn pruning into a ``TypeError``.

    Args:
        indexes: Iterable of requested message indexes.

    Returns:
        list: Numeric indexes sorted ascending, followed by the remaining
        values sorted by their string representation.
    """
    numeric = []
    others = []
    for index in indexes:
        if isinstance(index, int) or isinstance(index, float):
            numeric.append(index)
        else:
            others.append(index)
    return sorted(numeric) + sorted(others, key=str)


def _tool_reply_indexes(views: list, owner_index: int, tool_call_ids: list) -> list:
    """Collect indexes of ``role="tool"`` replies after ``owner_index``.

    Only replies whose ``tool_call_id`` is declared by the assistant message at
    ``owner_index`` are collected, so a tool group is never partially kept.

    Args:
        views (list): Normalized message views in chronological order.
        owner_index (int): Index of the assistant message carrying ``tool_calls``.
        tool_call_ids (list): Ids declared by that assistant message.

    Returns:
        list: Indexes of the matching tool messages, in ascending order.
    """
    replies = []
    for index in range(owner_index + 1, len(views)):
        msg = views[index]
        if not msg or msg.get("role") != ROLE_TOOL:
            continue
        tool_call_id = msg.get("tool_call_id")
        if tool_call_id and tool_call_id in tool_call_ids:
            replies.append(index)
    return replies


def expand_indexes_for_tool_pairing(messages: list, indexes: list, logger=None) -> list:
    """Expand requested delete indexes into complete tool-call groups.

    Index-based pruning is used by ``/ctx.del_msg`` and by the agent-facing
    context-cut tool. Deleting only the assistant message carrying
    ``tool_calls`` leaves its ``role="tool"`` observations orphaned, and
    deleting only one tool observation leaves a dangling ``tool_calls``; either
    shape makes providers reject the whole request with errors such as
    ``No tool call found for function call output with call_id ...``.

    For every requested index this helper adds the messages required to keep
    the tool-call group intact: the tool replies of a selected assistant
    message, and the owning assistant message plus all of its sibling replies
    for a selected tool message. Requested indexes are always kept in the
    result (including out-of-range ones) so callers keep their existing
    filtering behaviour.

    Args:
        messages (list): Messages in chronological order, the same list the
        caller is about to prune. Indexes are relative to this list.
        indexes (list): Requested message indexes.
        logger: Optional logger used to record every extra index pulled in.

    Returns:
        list: Sorted unique indexes covering every affected tool-call group.
    """
    if not indexes:
        return []
    if not messages:
        return _sort_indexes(set(indexes))

    views = [_message_view(msg) for msg in messages]
    total = len(views)

    expanded = set()
    extra = set()
    for index in indexes:
        expanded.add(index)
        if not isinstance(index, int) or index < 0 or index >= total:
            continue
        msg = views[index]
        if not msg:
            continue

        role = msg.get("role")
        if role == ROLE_ASSISTANT:
            tool_call_ids = extract_tool_call_ids(msg)
            if not tool_call_ids:
                continue
            group = _tool_reply_indexes(views, index, tool_call_ids)
        elif role == ROLE_TOOL:
            tool_call_id = msg.get("tool_call_id")
            if not tool_call_id:
                continue
            owner = _tool_call_owner_index(views, tool_call_id, index, 0)
            if owner is None:
                continue
            group = [owner] + _tool_reply_indexes(
                views, owner, extract_tool_call_ids(views[owner]),
            )
        else:
            continue

        for group_index in group:
            if group_index in expanded:
                continue
            expanded.add(group_index)
            extra.add(group_index)

    if extra and logger:
        logger.warning(
            "expand delete indexes for tool-call pairing: extra=%s reason=%s",
            _sort_indexes(extra),
            "keep tool_calls/tool_call_id group intact",
        )
    return _sort_indexes(expanded)
