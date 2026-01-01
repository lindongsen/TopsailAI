'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose:
'''

import os

def get_extra_tools():
    """
    return string for prompt content of extra tools
    """
    result = ""
    extra_tools = os.getenv("EXTRA_TOOLS")
    if extra_tools:
       # split by ';'
       extra_tools = extra_tools.split(';')
    for tool_prompt_file in extra_tools or []:
        tool_prompt_file = tool_prompt_file.strip()
        if not tool_prompt_file:
            continue
        if not os.path.exists(tool_prompt_file):
            continue
        result += read_prompt(tool_prompt_file)
    result = result.strip()
    if not result:
        return ""
    return \
    f"""
# Extra Tools Start

{result}

# Extra Tools End
---
"""

def get_prompt_file_path(relative_path):
    file_path = relative_path
    if not os.path.exists(file_path):
        file_path = os.path.join(
            os.path.dirname(__file__), relative_path
        )
    return file_path

def exists_prompt_file(relative_path) -> bool:
    fpath = get_prompt_file_path(relative_path)
    return os.path.exists(fpath)

def read_prompt(relative_path):
    """ return string for file content.

    :relative_path: e.g. 'work_mode/format/json.md'
    """
    file_path = get_prompt_file_path(relative_path)
    with open(file_path) as fd:
        content = fd.read().strip()
        if content:
            # add split line to tail
            if content.endswith("===") or content.endswith("---"):
                content += "\n"
            else:
                content += "\n---\n\n"
            return content

    return ""

def is_only_pure_system_prompt() -> bool:
    """ only the working mode. """
    return os.getenv("PURE_SYSTEM_PROMPT", "0") == "1"


class PromptHubExtractor(object):
    """ a extractor to get prompt """

    # basic
    prompt_common = (
        read_prompt("security/file.md")
        + read_prompt("context/file.md")
        + read_prompt("search/text.md")
    ) if not is_only_pure_system_prompt() else ""

    # task management
    prompt_task = (
        read_prompt("task/control.md")
        + read_prompt("task/tracking.md")
    ) if not is_only_pure_system_prompt() else ""

    # interactive, json
    prompt_interactive_json = read_prompt("work_mode/format/json.md")

    # interactive, topsailai
    prompt_interactive_topsailai = read_prompt("work_mode/format/topsailai.md")

    # use tool calls
    prompt_use_tool_calls = read_prompt("tools/use_tool_calls.md")

    # work-mode ReAct
    prompt_mode_ReAct_base = (
        read_prompt("work_mode/ReAct.md")
        + prompt_common
        + prompt_task
    )

    prompt_mode_ReAct_toolCall = (
        prompt_mode_ReAct_base
        + read_prompt("work_mode/format/topsailai2.md")
        + prompt_use_tool_calls
    )

    prompt_mode_ReAct_toolPrompt = (
        prompt_mode_ReAct_base

        # place them to tail
        #+ prompt_interactive_json
        #+ read_prompt("work_mode/format/json_ReAct.md")
        + prompt_interactive_topsailai
        + read_prompt("work_mode/format/topsailai_ReAct.md")
    )

    # work-mode PlanAndExecute
    prompt_mode_PlanAndExecute = (
        read_prompt("work_mode/PlanAndExecute.md")
        + prompt_common
        + prompt_task
        + read_prompt("work_mode/sop/sub_tasks.md")

        # place them to tail
        + prompt_interactive_json
        + read_prompt("work_mode/format/json_PlanAndExecute.md")
    )

def disable_tools(raw_tools:list[str], target_tools:list[str]):
    """ return available tools """
    if not raw_tools:
        return raw_tools
    new_tools = raw_tools[:]
    target_tools = set(target_tools)
    for raw_tool_name in raw_tools:
        raw_tool_name = raw_tool_name.strip()
        if not raw_tool_name:
            continue
        for disabled_tool_name in target_tools:
            disabled_tool_name = disabled_tool_name.strip()
            if not disabled_tool_name:
                continue
            if raw_tool_name.startswith(disabled_tool_name):
                new_tools.remove(raw_tool_name)
                break
    return new_tools

def disable_tools_by_env(raw_tools:list[str]):
    """ return available tools """
    if not raw_tools:
        return raw_tools
    env_target_tools = os.getenv("DISABLED_TOOLS")
    if not env_target_tools:
        return raw_tools
    env_target_tools = env_target_tools.replace(',', ';').split(';')
    return disable_tools(raw_tools, env_target_tools)

def enable_tools(raw_tools:list[str], target_tools:list[str]):
    """ return available tools """
    if not raw_tools:
        return raw_tools
    new_tools = set()
    target_tools = set(target_tools)
    for raw_tool_name in raw_tools:
        raw_tool_name = raw_tool_name.strip()
        if not raw_tool_name:
            continue
        for enabled_tool_name in target_tools:
            enabled_tool_name = enabled_tool_name.strip()
            if not enabled_tool_name:
                continue
            if raw_tool_name.startswith(enabled_tool_name):
                new_tools.add(raw_tool_name)
                break
    return list(new_tools)

def enable_tools_by_env(raw_tools:list[str]):
    """ return available tools """
    if not raw_tools:
        return raw_tools
    env_target_tools = os.getenv("ENABLED_TOOLS")
    if not env_target_tools:
        return raw_tools
    env_target_tools = env_target_tools.replace(',', ';').split(';')
    return enable_tools(raw_tools, env_target_tools)

def get_tools_by_env(raw_tools:list[str]):
    """ return available tools """
    if not raw_tools:
        return raw_tools

    # enabled first
    tools = enable_tools_by_env(raw_tools)

    # disabled secondary
    tools = disable_tools_by_env(tools)

    return tools

def get_prompt_from_module(module_name:str, key:str="PROMPT") -> str:
    """
    Args:
        module_name (str): name from tools, e.g. agent_tool, cmd_tool
        key (str, optional): Defaults to "PROMPT".

    Returns:
        str: prompt content.
    """
    try:
        m = __import__(f"topsailai.tools.{module_name}", None, None, [module_name])
        return getattr(m, key)
    except Exception:
        pass
    return ""

def get_prompt_by_tools(tools:list[str]) -> str:
    """ return prompt content from prompt_hub """
    prompt_keys = set()
    prompt_content = ""

    modules = set()
    for tool_name in tools:
        # tool_name: agent_tool.WritingAssistant
        module_name = tool_name.split('.', 1)[0]
        modules.add(module_name)

    for module_name in modules:
        # from prompt_hub
        key = f"tools/{module_name}.md"
        if exists_prompt_file(key):
            prompt_keys.add(key)

        # from tools.module
        tool_prompt = get_prompt_from_module(module_name)
        if tool_prompt:
            prompt_content += tool_prompt.strip() + "\n\n"

    for key in prompt_keys:
        prompt_content += read_prompt(key)

    return prompt_content
