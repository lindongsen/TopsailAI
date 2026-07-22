'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-22
Purpose: Fix common trailing garbage produced by Kimi models.
'''

import os
import re

from topsailai.utils.thread_local_tool import get_agent_object


# Kimi sometimes appends trailing garbage such as `` ` <|tool_call_end|><|tool_calls_section_end|> `` to tool-call
# responses. This pattern matches an optional backtick, optional whitespace,
# the literal garbage characters, and any trailing whitespace at the end of a
# string.
TRAILING_GARBAGE_PATTERN = re.compile(r'[`\s]*<\|tool_call_end\|><\|tool_calls_section_end\|>\s*$')


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


def _is_kimi_model(model_name):
    """Return True when *model_name* identifies a Kimi model."""
    if not model_name:
        return False
    return str(model_name).lower().startswith("kimi")


def _strip_trailing_garbage(text):
    """Strip Kimi trailing garbage from a string.

    Args:
        text (str): The text to clean.

    Returns:
        str: The cleaned text. If no garbage is present, returns *text*
        unchanged.
    """
    return TRAILING_GARBAGE_PATTERN.sub("", text)


def fix_kimi_trailing_garbage(message, rsp_obj=None, **_):
    """Remove Kimi-specific trailing garbage from action messages.

    This handler only runs when the current LLM model is identified as Kimi.
    It processes ``list_dict`` messages and, for each item with
    ``step_name == 'action'``, strips trailing garbage such as
    `` ` <|tool_call_end|><|tool_calls_section_end|> `` from the ``raw_text`` string.

    Important ordering limitation:
        ``check_or_fix_mistakes`` stops after the first handler that modifies
        the response. Because this handler sorts before
        ``missing_tool_args.fix_mistake*``, a Kimi response that has both
        trailing garbage and missing ``tool_args`` wrapping will only have the
        garbage stripped. If both errors commonly co-occur, the chaining logic
        in ``check_or_fix_mistakes`` should be revisited.

    Args:
        message (str | list | dict): The LLM response to fix.
        rsp_obj (any, optional): Raw response object, used as a secondary
            model-name signal.

    Returns:
        list | None: The modified message if any change was made, otherwise
        ``None``.
    """
    model_name = _get_current_model_name(rsp_obj=rsp_obj)
    if not _is_kimi_model(model_name):
        return None

    if not isinstance(message, list):
        return None

    changed = False
    for item in message:
        if not isinstance(item, dict):
            continue
        if item.get("step_name") != "action":
            continue

        raw_text = item.get("raw_text")
        if not isinstance(raw_text, str):
            continue

        cleaned = _strip_trailing_garbage(raw_text)
        if cleaned != raw_text:
            item["raw_text"] = cleaned
            changed = True

    return message if changed else None


MISTAKES = dict(
    fix_kimi_trailing_garbage=fix_kimi_trailing_garbage,
)
