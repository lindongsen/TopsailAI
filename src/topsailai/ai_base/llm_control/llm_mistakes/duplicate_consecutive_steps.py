'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-27
Purpose: Remove consecutive duplicate action steps from parsed LLM responses.
'''

import simplejson

from topsailai.logger.log_chat import logger


def _normalize_action_item(item):
    """Return a hashable signature for an action item.

    The signature is based on ``tool_call`` and a JSON-normalized,
    sort-keyed representation of ``tool_args``. This makes the comparison
    robust against whitespace, key ordering, and numeric type differences
    that can appear in raw LLM output.

    Args:
        item (dict): A parsed response item.

    Returns:
        tuple | None: A ``(tool_call, normalized_args)`` tuple if the item
        is a valid action step, otherwise ``None``.
    """
    if not isinstance(item, dict):
        return None
    if item.get("step_name") != "action":
        return None
    tool_call = item.get("tool_call")
    if not isinstance(tool_call, str):
        return None

    tool_args = item.get("tool_args")
    # Missing tool_args is intentionally treated as an empty dict so that
    # two consecutive actions with the same tool_call and no arguments are
    # still considered duplicates.
    if tool_args is None:
        tool_args = {}
    if not isinstance(tool_args, (dict, list)):
        return None

    try:
        normalized = simplejson.dumps(
            tool_args,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return None

    return (tool_call, normalized)


def _remove_consecutive_duplicate_actions(response):
    """Remove consecutive duplicate action steps from a parsed response list.

    The function performs a single left-to-right pass. Whenever two
    consecutive action items have the same normalized ``tool_call`` and
    ``tool_args`` signature, the earlier item is removed. After a removal,
    the next comparison uses the item that followed the removed one, which
    matches the example behavior:

        [action1, action2, action3] where action1==action2 and action2==action3
        -> delete action1, then compare action2 with action3 and delete action2.

    Args:
        response (list): Parsed LLM response list.

    Returns:
        list | None: A new list with duplicates removed, or ``None`` if no
        duplicates were found.
    """
    if not isinstance(response, list) or len(response) < 2:
        return None

    result = []
    changed = False

    for index in range(len(response) - 1):
        current = response[index]
        next_item = response[index + 1]

        current_sig = _normalize_action_item(current)
        next_sig = _normalize_action_item(next_item)

        if current_sig is not None and current_sig == next_sig:
            # Skip the current (earlier) duplicate action.
            changed = True
            continue

        result.append(current)

    # Always append the last item; it was never the "earlier" duplicate.
    result.append(response[-1])

    return result if changed else None


def fix_duplicate_consecutive_steps(message, **_):
    """Fix consecutive duplicate action steps in a parsed LLM response.

    This handler is model-agnostic and operates on already-parsed
    ``list[dict]`` responses. It runs after other fixers that normalize
    action content, so ``tool_args`` are expected to be present and
    well-formed before duplication detection runs.

    Any exception raised by the deduplication logic is caught and logged;
    the original message is returned unchanged so that a bug in this fixer
    cannot break the upstream ``format_response()`` flow.

    Args:
        message (str | list | dict): The LLM response to fix.

    Returns:
        list | None: The deduplicated response if duplicates were found and
        removed, otherwise ``None`` (or the original message if an exception
        occurred).
    """
    if not isinstance(message, list):
        return None

    try:
        return _remove_consecutive_duplicate_actions(message)
    except Exception as e:
        logger.exception(
            "duplicate_consecutive_steps fixer failed: %s",
            e,
        )
        return message


MISTAKES = dict(
    fix_duplicate_consecutive_steps=fix_duplicate_consecutive_steps,
)
