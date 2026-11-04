'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-04
  Purpose: writer/programmer assistant helpers extracted from tools/agent_tool.py.
'''

import os

from topsailai.utils import file_tool
from topsailai.prompt_hub import prompt_tool
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE
from topsailai.tools.tool_utils.parameter import resolve_str_param

DEFAULT_WORKSPACE = FOLDER_WORKSPACE


def is_code_file(file_path:str) -> bool:
    """Return False for documentation-like suffixes, True otherwise."""
    if not file_path:
        return False

    file_path = file_path.lower()
    for suffix in [".md", ".manifest", ".json", ".readme"]:
        if file_path.endswith(suffix):
            return False

    return True

def get_all_agent_tools():
    """ return dict, key is tool_name, value is tool_func. """
    from topsailai.tools.base.init import TOOLS as INTERNAL_TOOLS

    agent_tools = {}
    for tool_name, tool_func in INTERNAL_TOOLS.items():
        if tool_name.startswith("agent"):
            agent_tools[tool_name] = tool_func
    return agent_tools


def _agent_writer(
        msg_or_file:str,
        model_name:str=None,
        workspace:str=DEFAULT_WORKSPACE,

        # internal only. DONOT WRITING TO DOC
        tools:list=None,
        more_prompt:str="\nYou are a professional writer.\n",
        system_prompt:str="",
    ):
    """ A professional Assistant for writer.
    The writing assistant can read a large amount of text content.
    There are no restrictions for scenarios that may generate substantial text,
    such as reading large files or fetching web content via cURL.
    The text will not be forcibly truncated.

    Args:
        msg_or_file (str): it can be message or file path.
            if user pass a file path, the content of the file will be read as message.
            if the user does explicitly specify a file, should use it directly.
        model_name (str): LLM name, If the user does not explicitly specify, this parameter is not needed.
        workspace (str): a folder absolute path for workspace.

    Return final answer.
    """
    message = msg_or_file
    # read message from file if msg_or_file is a file path
    if msg_or_file[0] in ["/", "."]:
        if os.path.isfile(msg_or_file):
            with open(msg_or_file, "r", encoding="utf-8") as f:
                message = f.read()

    workspace = workspace.strip()
    if workspace:
        if 'workspace' not in message or '工作空间' not in message:
            message += f"\n----\nworkspace:`{workspace}`\n"

    from topsailai.ai_base.agent_base import AgentRun
    from topsailai.ai_base.agent_types.react import SYSTEM_PROMPT, Step4ReAct

    _, system_prompt_content = file_tool.get_file_content_fuzzy(system_prompt)
    _, more_prompt_content = file_tool.get_file_content_fuzzy(more_prompt)
    if not system_prompt_content:
        system_prompt_content = SYSTEM_PROMPT
    system_prompt_content += more_prompt_content

    agent = AgentRun(
        system_prompt=system_prompt_content,
        tools=tools,
        agent_name="AgentWriter",
        excluded_tool_kits=["agent_tool"],
    )
    llm_model = agent.runtime.llm_model
    llm_model.max_tokens = max(1600, llm_model.max_tokens)
    llm_model.temperature = max(0.97, llm_model.temperature)
    if model_name:
        llm_model.model_name = model_name
    return agent.run(Step4ReAct(), message)

def agent_writer(msg_or_file:str, model_name:str=None, workspace:str=DEFAULT_WORKSPACE):
    """ A professional Assistant for writer.
    The writing assistant can read a large amount of text content.
    There are no restrictions for scenarios that may generate substantial text,
    such as reading large files or fetching web content via cURL.
    The text will not be forcibly truncated.

    Args:
        msg_or_file (str): it can be message or file path.
            if user pass a file path, the content of the file will be read as message.
            if the user does explicitly specify a file, should use it directly.
        model_name (str): LLM name, If the user does not explicitly specify, this parameter is not needed.
        workspace (str): a folder absolute path for workspace.

    Return final answer.
    """
    msg_or_file, error = resolve_str_param(msg_or_file, "msg_or_file")
    if error:
        return error
    if model_name is not None:
        model_name, error = resolve_str_param(model_name, "model_name")
        if error:
            return error
    workspace, error = resolve_str_param(workspace, "workspace")
    if error:
        return error
    return _agent_writer(
        msg_or_file=msg_or_file,
        model_name=model_name,
        workspace=workspace,
    )

def agent_programmer(
        msg_or_file:str, model_name:str=None, workspace:str=DEFAULT_WORKSPACE,
        system_prompt:str="",
    ):
    """ A professional Assistant for programmer.

    Args:
        msg_or_file (str): it can be message or file path for a TASK.
            if user pass a file path, the content of the file will be read as message.
            if the user does explicitly specify a file, should use it directly.

        model_name (str): LLM name, If the user does not explicitly specify, this parameter is not needed.
        workspace (str): a folder absolute path for workspace.
        system_prompt (str): it can be content or a filepath; If the user does not explicitly specify, this parameter is not needed.

    Return final answer.
    """
    msg_or_file, error = resolve_str_param(msg_or_file, "msg_or_file")
    if error:
        return error
    if model_name is not None:
        model_name, error = resolve_str_param(model_name, "model_name")
        if error:
            return error
    workspace, error = resolve_str_param(workspace, "workspace")
    if error:
        return error
    system_prompt, error = resolve_str_param(system_prompt, "system_prompt")
    if error:
        return error

    message = msg_or_file
    # read message from file if msg_or_file is a file path
    if msg_or_file and msg_or_file[0] in ["/", "."]:
        if os.path.isfile(msg_or_file) and not is_code_file(msg_or_file):
            with open(msg_or_file, "r", encoding="utf-8") as f:
                message = f.read()

    if not message.strip():
        return "null of message content"

    workspace = workspace.strip()
    if workspace:
        if 'workspace' not in message or '工作空间' not in message:
            message += f"\n----\nworkspace:`{workspace}`\n"

    # system prompt
    if system_prompt and system_prompt[0] in ["/", "."]:
        if os.path.isfile(system_prompt):
            with open(system_prompt, encoding="utf-8") as fd:
                system_prompt = fd.read()

    from topsailai.ai_base.agent_base import AgentRun
    from topsailai.ai_base.agent_types.react import SYSTEM_PROMPT, Step4ReAct
    agent = AgentRun(
        system_prompt=(
            SYSTEM_PROMPT +
            prompt_tool.read_prompt("project/programmer/folder.md") +
            system_prompt +
            "\nYou are a professional programmer.\n"
        ),
        tools=None,
        agent_name="AgentProgrammer",
        excluded_tool_kits=["agent_tool"],
    )
    if model_name:
        agent.runtime.llm_model.model_name = model_name
    return agent.run(Step4ReAct(), message)
