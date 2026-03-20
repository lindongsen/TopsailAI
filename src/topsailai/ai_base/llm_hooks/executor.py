'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-29
  Purpose:
'''

from topsailai.utils import (
    module_tool,
    env_tool,
    thread_local_tool,
)

def get_hooks_runtime(key:str) -> list[str]:
    agent = thread_local_tool.get_agent_object()
    model_name = None

    if agent is None:
        model_name = env_tool.EnvReaderInstance.get("OPENAI_MODEL") or env_tool.EnvReaderInstance.get("AI_MODEL")
    else:
        model_name = agent.llm_model.model_name

    if not model_name:
        return []

    model_name_lower = str(model_name).lower()

    if model_name_lower.startswith("kimi"):
        if key == "TOPSAILAI_HOOK_AFTER_LLM_CHAT":
            return [
                "topsailai.ai_base.llm_hooks.hook_after_chat.kimi"
            ]

    if model_name_lower.startswith("minimax"):
        if key == "TOPSAILAI_HOOK_AFTER_LLM_CHAT":
            return [
                "topsailai.ai_base.llm_hooks.hook_after_chat.minimax"
            ]
        if key == "TOPSAILAI_HOOK_BEFORE_LLM_CHAT":
            if model_name == "MiniMax-M2.5":
                return [
                    "topsailai.ai_base.llm_hooks.hook_before_chat.only_one_system_message",
                ]
    return []

def hook_execute(key:str, content:str|list) -> list[dict]|str:
    """ execute hooks

    Args:
        key (str): e.g TOPSAILAI_HOOK_AFTER_LLM_CHAT
        content (str|list): content from llm

    Returns:
        list[dict]|str
    """
    hooks = env_tool.EnvReaderInstance.get_list_str(key) or get_hooks_runtime(key)
    if not hooks:
        return content
    for hook_path in hooks:
        hook_func = module_tool.get_var(hook_path, "hook_execute")
        if hook_func:
            content = hook_func(content)
    return content
