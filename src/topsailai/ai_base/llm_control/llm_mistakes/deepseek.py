'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-28
Purpose: Fix DeepSeek-specific DSML tool-call output format.
'''

import os

import simplejson

from topsailai.utils.thread_local_tool import get_agent_object


DSML_TOOL_CALLS_OPEN = "<｜DSML｜tool_calls>"
DSML_TOOL_CALLS_CLOSE = "</｜DSML｜tool_calls>"
DSML_INVOKE_OPEN = "<｜DSML｜invoke"
DSML_INVOKE_CLOSE = "</｜DSML｜invoke>"
DSML_PARAMETER_OPEN = "<｜DSML｜parameter"
DSML_PARAMETER_CLOSE = "</｜DSML｜parameter>"


def _get_current_model_name(rsp_obj=None):
    """Resolve the current LLM model name from agent context or environment.

    The primary source is the agent object stored in thread-local storage,
    which is set by ``AgentBase.run`` during agent execution. If no agent is
    running (for example when ``llm_shell`` is used directly), fall back to
    the ``OPENAI_MODEL`` environment variable. An optional ``rsp_obj`` can
    provide a secondary signal via its ``model`` attribute.

    Args:
        rsp_obj (any, optional): Raw response object from the SDK.

    Returns:
        str: The resolved model name, or an empty string if unknown.
    """
    agent = get_agent_object()
    if agent is not None:
        llm_model = getattr(agent, "llm_model", None)
        if llm_model is not None:
            model_name = getattr(llm_model, "model_name", None)
            if model_name:
                return str(model_name)

    if rsp_obj is not None:
        model_name = getattr(rsp_obj, "model", None)
        if model_name:
            return str(model_name)

    return os.getenv("OPENAI_MODEL", "")


def _is_deepseek_model(model_name):
    """Return True when *model_name* identifies a DeepSeek model."""
    if not model_name:
        return False
    return str(model_name).lower().startswith("deepseek")


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


def _parse_dsml_tool_calls(response):
    """Parse DeepSeek's DSML tool-call format into standard action steps.

    The expected format is::

        <｜DSML｜tool_calls>
        <｜DSML｜invoke name="tool-name">
        <｜DSML｜parameter name="arg-name" string="true|false">value</｜DSML｜parameter>
        ...
        </｜DSML｜invoke>
        ...
        </｜DSML｜tool_calls>

    Leading text before the ``<｜DSML｜tool_calls>`` tag is preserved as a
    ``thought`` step. Each ``invoke`` block becomes an ``action`` step with
    ``tool_call`` and ``tool_args`` keys.

    Args:
        response (str): The raw LLM response string.

    Returns:
        list | None: A list of standardized steps, or ``None`` if the input
        does not contain a well-formed DSML tool_calls block.
    """
    if not isinstance(response, str):
        return None

    start_idx = response.find(DSML_TOOL_CALLS_OPEN)
    if start_idx < 0:
        return None

    close_idx = response.find(DSML_TOOL_CALLS_CLOSE, start_idx)
    if close_idx < 0:
        return None

    leading_text = response[:start_idx].strip()
    block = response[start_idx + len(DSML_TOOL_CALLS_OPEN):close_idx]

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

    result = []
    if leading_text:
        result.append({"step_name": "thought", "raw_text": leading_text})
    result.extend(actions)
    return result


def fix_deepseek_dsml_tool_calls(message, rsp_obj=None, **_):
    """Parse DeepSeek DSML tool-call blocks into standard action steps.

    This handler only runs when the current LLM model is identified as
    DeepSeek. It converts the custom XML-like DSML format produced by some
    DeepSeek deployments into the standard list-of-dictionaries format used
    by the rest of the pipeline.

    Args:
        message (str | list | dict): The LLM response to fix.
        rsp_obj (any, optional): Raw response object, used as a secondary
            model-name signal.

    Returns:
        list | None: The parsed action steps if the input is a DeepSeek DSML
        string, otherwise ``None``.
    """
    model_name = _get_current_model_name(rsp_obj=rsp_obj)
    if not _is_deepseek_model(model_name):
        return None

    if not isinstance(message, str):
        return None

    return _parse_dsml_tool_calls(message)


MISTAKES = dict(
    fix_deepseek_dsml_tool_calls=fix_deepseek_dsml_tool_calls,
)
