"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-16
Purpose: Semantic message comparison helpers used across layers.
"""

from topsailai.utils import json_tool


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
