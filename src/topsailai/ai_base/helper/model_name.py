'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-30
Purpose: Shared helpers for resolving the current LLM model name.
'''

import os

from topsailai.utils.thread_local_tool import get_agent_object


def get_current_model_name(rsp_obj=None):
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
