'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-04
  Purpose: story-memory helpers extracted from tools/agent_tool.py.
'''

import threading

from topsailai.utils.json_tool import json_dump
from topsailai.utils.cmd_tool import exec_cmd_in_new_process
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.utils import thread_local_tool
from topsailai.tools.agent_tool_utils.writer import (
    DEFAULT_WORKSPACE,
    _agent_writer,
)


def agent_memory_as_story(
        msg_or_file:str,
        model_name:str=None,
        workspace:str=None,
    ):
    """ A professional Assistant for writer.
    Core Goal: Summarize the messages and generate appropriate a title and content.

    Args:
        msg_or_file (str): it can be message or file path.
            if pass a file path, the content of the file will be read as message.
            if the user does explicitly specify a file, should use it directly.
        model_name (str): LLM name, If the user does not explicitly specify, this parameter is not needed.
        workspace (str): a folder absolute path for workspace.

    Return final answer.
    """
    if not model_name:
        model_name = EnvReaderInstance.get("TOPSAILAI_STORY_MODEL")

    if not workspace:
        workspace = EnvReaderInstance.get("TOPSAILAI_STORY_WORKSPACE")

    if not workspace:
        workspace = DEFAULT_WORKSPACE

    from topsailai.tools import story_tool
    from topsailai.tools.base.common import format_tools_map

    prompt = story_tool.PROMPT_SUMMARY_AS_STORY

    return _agent_writer(
        msg_or_file=msg_or_file,
        model_name=model_name,
        workspace=workspace,
        tools=format_tools_map(story_tool.TOOLS, "story_tool"),
        more_prompt=prompt,
    )

def subprocess_agent_memory_as_story(
        msg_or_file,
        model_name:str=None,
        workspace:str=None,
    ) -> int | None:
    """ return pid """
    if not msg_or_file:
        return None

    if not model_name:
        model_name = EnvReaderInstance.get("TOPSAILAI_STORY_MODEL")

    if not workspace:
        workspace = EnvReaderInstance.get("TOPSAILAI_STORY_WORKSPACE")

    if isinstance(msg_or_file, (list, dict, set)):
        msg_or_file = json_dump(msg_or_file)

    args = ["topsailai_agent_story", "-m", msg_or_file]
    if model_name:
        args += ["-M", model_name]
    if workspace:
        args += ["-w", workspace]

    return exec_cmd_in_new_process(
        args,
        env=dict(
            PURE_SYSTEM_PROMPT="1",
            TOPSAILAI_STORY_PROMPT=EnvReaderInstance.get("TOPSAILAI_STORY_PROMPT", ""),
            ENABLED_TOOLS="story_tool",
            EXTRA_TOOLS="",
            PLUGIN_TOOLS="",
            DEBUG="0",
        )
    )

def async_agent_memory_as_story(
        msg_or_file,
        model_name:str=None,
        workspace:str=None,
    ):
    if isinstance(msg_or_file, (list, dict, set)):
        msg_or_file = json_dump(msg_or_file)

    def func_call():
        # disabled debug in this thread
        thread_local_tool.set_thread_var(
            thread_local_tool.KEY_FLAG_DEBUG, 0
        )
        agent_memory_as_story(
            msg_or_file=msg_or_file,
            model_name=model_name,
            workspace=workspace,
        )
    threading.Thread(target=func_call, name="async_agent_memory_as_story", daemon=False).start()
    return
