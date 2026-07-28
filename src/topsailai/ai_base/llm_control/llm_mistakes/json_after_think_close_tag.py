'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-28
Purpose: Fix responses that place a JSON action after a think-close tag.
'''

import simplejson

from topsailai.ai_base.llm_control.llm_mistakes.kimi import THINKING_CLOSE


THINKING_CLOSE_TAGS = ("</thinking>", THINKING_CLOSE)


def _split_at_thinking_close(text):
    """Split *text* at the first thinking-close tag.

    Args:
        text (str): The text to split.

    Returns:
        tuple | None: ``(leading_text, trailing_text)`` if a tag is found and
        there is trailing content, otherwise ``None``.
    """
    if not isinstance(text, str):
        return None

    first_pos = -1
    first_tag = None
    for tag in THINKING_CLOSE_TAGS:
        pos = text.find(tag)
        if pos >= 0 and (first_pos == -1 or pos < first_pos):
            first_pos = pos
            first_tag = tag

    if first_pos == -1:
        return None

    trailing = text[first_pos + len(first_tag):]
    if not trailing.strip():
        return None

    leading = text[:first_pos].strip()
    return leading, trailing.strip()


def _parse_action_json(text):
    """Parse a JSON object containing ``tool_call`` and ``tool_args``.

    Args:
        text (str): The JSON text to parse.

    Returns:
        dict | None: ``{"tool_call": ..., "tool_args": ...}`` or ``None``.
    """
    try:
        data = simplejson.loads(text, strict=False)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    tool_call = data.get("tool_call")
    tool_args = data.get("tool_args")
    if not isinstance(tool_call, str) or not isinstance(tool_args, dict):
        return None

    return {"tool_call": tool_call, "tool_args": tool_args}


def fix_json_after_thinking_close(message, **_):
    """Extract a JSON action that follows a thinking-close tag.

    Some models emit free text or reasoning, then a thinking-close marker,
    then a JSON object with ``tool_call`` and ``tool_args``. This handler
    splits that pattern into a ``thought`` step (leading text) and an
    ``action`` step (parsed JSON).

    Args:
        message (str | list | dict): The LLM response to fix.

    Returns:
        list | None: A list with ``[thought, action]`` or ``[action]`` if
        the pattern matches, otherwise ``None``.
    """
    if not isinstance(message, str):
        return None

    split = _split_at_thinking_close(message)
    if split is None:
        return None

    leading_text, trailing_text = split
    action = _parse_action_json(trailing_text)
    if action is None:
        return None

    result = []
    if leading_text:
        result.append({"step_name": "thought", "raw_text": leading_text})
    result.append({
        "step_name": "action",
        "tool_call": action["tool_call"],
        "tool_args": action["tool_args"],
    })
    return result


MISTAKES = dict(
    fix_json_after_thinking_close=fix_json_after_thinking_close,
)
