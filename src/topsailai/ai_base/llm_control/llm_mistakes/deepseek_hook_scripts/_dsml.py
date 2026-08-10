"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-10
Purpose: Shared DSML invoke/parameter parsing helper for DeepSeek hook scripts.

This module is intentionally prefixed with an underscore so that the hook-script
runner never treats it as an executable case script. It provides a
wrapper-independent parser that converts DSML ``invoke`` blocks into canonical
agent ``action`` steps.
"""

import simplejson


DSML_TOOL_CALLS_OPEN = "<｜DSML｜tool_calls>"
DSML_TOOL_CALLS_CLOSE = "</｜DSML｜tool_calls>"
DSML_INVOKE_OPEN = "<｜DSML｜invoke"
DSML_INVOKE_CLOSE = "</｜DSML｜invoke>"
DSML_PARAMETER_OPEN = "<｜DSML｜parameter"
DSML_PARAMETER_CLOSE = "</｜DSML｜parameter>"


def _parse_attribute(text, name):
    """Extract a double-quoted attribute value from an XML-like opening tag.

    Args:
        text (str): The opening tag text, e.g. ``'<invoke name="foo">'``.
        name (str): The attribute name to look for.

    Returns:
        str | None: The attribute value, or ``None`` if not found.
    """
    prefix = f'{name}="'
    start = text.find(prefix)
    if start < 0:
        return None
    start += len(prefix)
    end = text.find('"', start)
    if end < 0:
        return None
    return text[start:end]


def _parse_parameter_value(value_text, string_attr):
    """Parse a DSML parameter value according to its ``string`` attribute.

    When ``string_attr`` is ``"false"`` the value is parsed as JSON; if JSON
    parsing fails the raw text is returned. When ``string_attr`` is anything
    else (including ``"true"`` or missing) the raw text is returned.

    Args:
        value_text (str): The raw parameter value.
        string_attr (str | None): The value of the ``string`` attribute.

    Returns:
        any: The parsed or raw value.
    """
    if string_attr is not None and string_attr.lower() == "false":
        try:
            return simplejson.loads(value_text, strict=False)
        except Exception:
            return value_text
    return value_text


def parse_dsml_invokes(block):
    """Parse DSML invoke blocks into canonical action steps.

    Args:
        block (str): The inner content between the ``tool_calls`` wrapper tags.

    Returns:
        list | None: A list of canonical ``action`` steps, or ``None`` if the
        block does not contain a well-formed invoke structure.
    """
    actions = []
    search_pos = 0
    while True:
        invoke_open_idx = block.find(DSML_INVOKE_OPEN, search_pos)
        if invoke_open_idx < 0:
            break

        invoke_tag_end = block.find(">", invoke_open_idx)
        if invoke_tag_end < 0:
            return None

        tool_call = _parse_attribute(
            block[invoke_open_idx:invoke_tag_end + 1], "name"
        )
        if not tool_call:
            return None

        invoke_close_idx = block.find(DSML_INVOKE_CLOSE, invoke_tag_end)
        if invoke_close_idx < 0:
            return None

        invoke_body = block[invoke_tag_end + 1:invoke_close_idx]
        tool_args = {}
        param_pos = 0
        while True:
            param_open_idx = invoke_body.find(DSML_PARAMETER_OPEN, param_pos)
            if param_open_idx < 0:
                break

            param_tag_end = invoke_body.find(">", param_open_idx)
            if param_tag_end < 0:
                return None

            param_name = _parse_attribute(
                invoke_body[param_open_idx:param_tag_end + 1], "name"
            )
            if not param_name:
                return None

            string_attr = _parse_attribute(
                invoke_body[param_open_idx:param_tag_end + 1], "string"
            )

            param_close_idx = invoke_body.find(DSML_PARAMETER_CLOSE, param_tag_end)
            if param_close_idx < 0:
                return None

            value_text = invoke_body[param_tag_end + 1:param_close_idx]
            tool_args[param_name] = _parse_parameter_value(value_text, string_attr)
            param_pos = param_close_idx + len(DSML_PARAMETER_CLOSE)

        actions.append({
            "step_name": "action",
            "tool_call": tool_call,
            "tool_args": tool_args,
        })
        search_pos = invoke_close_idx + len(DSML_INVOKE_CLOSE)

    if not actions:
        return None
    return actions


def parse_singular_wrapper(response, close_tag):
    """Parse a singular ``tool_call`` wrapper with a given close tag.

    Args:
        response (str): The raw LLM response string.
        close_tag (str): The expected closing tag, either ``</｜DSML｜tool_call>``
            or ``</｜DSML｜tool_calls>``.

    Returns:
        list | None: Canonical steps (optional leading thought + actions), or
        ``None`` if the response does not match this singular wrapper.
    """
    if not isinstance(response, str):
        return None

    malformed_open = "<｜DSML｜tool_call>"
    start_idx = response.find(malformed_open)
    if start_idx < 0:
        return None

    leading_text = response[:start_idx].strip()
    malformed_response = response[start_idx:].strip()
    if not malformed_response.endswith(close_tag):
        return None

    body = malformed_response[len(malformed_open):-len(close_tag)].strip()
    if not body.startswith(DSML_INVOKE_OPEN):
        return None

    actions = parse_dsml_invokes(body)
    if not actions:
        return None

    if leading_text:
        actions.insert(0, {"step_name": "thought", "raw_text": leading_text})
    return actions
