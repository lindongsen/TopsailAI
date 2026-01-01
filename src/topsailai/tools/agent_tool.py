'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose:
'''

import os
import threading

from topsailai.logger import logger
from topsailai.utils.json_tool import json_dump, json_load
from topsailai.utils.format_tool import to_list
from topsailai.utils import thread_local_tool
from topsailai.utils.cmd_tool import exec_cmd_in_new_process
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.prompt_hub import prompt_tool
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE

DEFAULT_WORKSPACE = FOLDER_WORKSPACE


def is_code_file(file_path:str) -> bool:
    if not file_path:
        return False

    file_path = file_path.lower()
    for suffix in [".md", ".manifest", ".json", ".readme"]:
        if file_path.endswith(suffix):
            return False

    return True

def get_all_agent_tools():
    """ return dict, key is tool_name, value is tool_func. """
    from . import TOOLS as INTERNAL_TOOLS

    agent_tools = {}
    for tool_name, tool_func in INTERNAL_TOOLS.items():
        if tool_name.startswith("agent"):
            agent_tools[tool_name] = tool_func
    return agent_tools


def _agent_writer(
        msg_or_file:str,
        model_name:str=None,
        workspace:str=DEFAULT_WORKSPACE,
        tools:list=None,
        more_prompt:str="\nYou are a professional writer.\n",
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

    agent = AgentRun(
        system_prompt=SYSTEM_PROMPT + more_prompt,
        tools=tools,
        agent_name="AgentWriter",
        excluded_tool_kits=["agent_tool"],
    )
    agent.llm_model.max_tokens = max(1600, agent.llm_model.max_tokens)
    agent.llm_model.temperature = max(0.97, agent.llm_model.temperature)
    if model_name:
        agent.llm_model.model_name = model_name
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
    message = msg_or_file
    # read message from file if msg_or_file is a file path
    if msg_or_file[0] in ["/", "."]:
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
        agent.llm_model.model_name = model_name
    return agent.run(Step4ReAct(), message)

def async_multitasks_agent_writer(
        goal:str,
        goal_report_file:str=None,
        task_prompt_file:str=None, model_name:str=None, workspace:str=DEFAULT_WORKSPACE, **tasks
    ):
    """ A professional writing assistant capable of executing tasks concurrently.

    Example:
        WritingAssistantMultiTasks(
            goal={GOAL OR PLAN},
            goal_report_file={REPORT_FILE_PATH},
            task_prompt_file={FILE_PATH},
            model_name={LLM_NAME},
            workspace={FOLDER},
            task1={TASK1},
            task2={TASK2},
        )

    Args:
        goal (str): one goal, multiple tasks;
            These tasks will be executed concurrently by WritingAssistant;
            Finally, the goal will be called to summarize the execution results of these tasks.
        goal_report_file: the file path for saving the final report of this goal.
        task_prompt_file: a file path; This document is a supplementary explanation or task requirements.
        tasks: multiple args, format is 'key=value', value can be message or file path, key prefix name is 'task', example: task1=xxx, task2=yyy;
            if user pass a file path, the content of the file will be read as message.
            if the user does explicitly specify a file, should use it directly.

        model_name: LLM name, If the user does not explicitly specify, this parameter is not needed.
        workspace: a folder absolute path for workspace.

    Return final answer.
    """
    thrs = {}
    results = {}

    # thread control
    semaphore = threading.Semaphore(10)

    task_prompt = ""
    if task_prompt_file and os.path.exists(task_prompt_file):
        with open(task_prompt_file, encoding="utf-8") as fd:
            task_prompt = fd.read()

    if task_prompt:
        task_prompt += "\n\n----\n\n"

    def _execute_task(_key, *args, **kwargs):
        with semaphore:
            result = agent_writer(
                *args, **kwargs
            )
            results[_key]["result"] = result
        return

    for k, v in tasks.items():
        v = str(v)
        results[k] = {
            "task": v,
            "result": "task failed"
        }
        if k.lower().startswith("task"):
            thr = threading.Thread(
                name=f"async_multitasks_agent_writer.{k}",
                daemon=False,
                target=_execute_task,
                kwargs=dict(
                    _key=k,
                    msg_or_file=task_prompt + v,
                    model_name=model_name,
                    workspace=workspace,
                )
            )
            thrs[k] = thr
            thr.start()

    # wait all threads done
    for k, t in thrs.items():
        logger.info(f"task is running: [{k}]")
        t.join()
        logger.info(f"task is done: [{k}]")

    if goal[0] not in ["/", "."]:
        goal += (
            "\n\n----\n\n"
            + (f"saving the final report to the file:{goal_report_file}\n\n" if goal_report_file else "")
            + json_dump(results, indent=0)
            + "\n\n"
        )

    return agent_writer(goal, model_name=model_name, workspace=workspace)


def async_multitasks_agent_writer2(
        goal:str,
        goal_report_file:str,
        task_prompt_file:str,
        tasks_file_or_json:str,
        model_name:str=None,
        workspace:str=DEFAULT_WORKSPACE,
    ):
    """ A professional writing assistant capable of executing tasks concurrently.

    one goal, multiple tasks:
        These tasks will be executed concurrently by WritingAssistant;
        Finally, the goal will be called to summarize the execution results of these tasks.

    Example:
        WritingAssistantMultiTasks(
            goal={GOAL OR PLAN},
            goal_report_file={REPORT_FILE_PATH},
            task_prompt_file={PROMPT_FILE_PATH},
            tasks_file_or_json={TASKS_FILE_PATH} or {JSON_STRING},
            model_name={LLM_NAME},
            workspace={FOLDER}
        )

    Args:
        goal (str): one goal.
        goal_report_file: the file path for saving the final report of this goal.
        task_prompt_file: a file path; This document is a supplementary explanation or task requirements.
        tasks_file_or_json (str): a file path or a json string, if file path, its content is json string;
            The JSON string is a list, and this list is a collection of tasks.

        model_name: LLM name, If the user does not explicitly specify, this parameter is not needed.
        workspace: a folder absolute path for workspace.

    Return final answer.
    """
    tasks_content = tasks_file_or_json
    if tasks_file_or_json[0] in ["/", "."]:
        with open(tasks_file_or_json, encoding="utf-8") as fd:
            tasks_content = fd.read()
    assert tasks_content
    tasks = json_load(tasks_content)
    tasks_kv = {}
    for i, task in enumerate(to_list(tasks)):
        tasks_kv[f"task{i}"] = task

    return async_multitasks_agent_writer(
        goal=goal,
        goal_report_file=goal_report_file,
        task_prompt_file=task_prompt_file,
        model_name=model_name,
        workspace=workspace,
        **tasks_kv
    )

def agent_memory_as_story(
        msg_or_file:str,
        model_name:str=None,
        workspace:str=DEFAULT_WORKSPACE,
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
    from . import story_tool, format_tools_map

    prompt = (
        "\n"
        "You are a professional writer.\n"
        "Your Core Goal: Summarize the messages and generate appropriate a title and content.\n"
        "Use story_tool to save content.\n"
        "[Attention] story_id is title, also is filename, max length is 250, Cannot contain any special characters other than '_-'\n"
    )
    prompt += EnvReaderInstance.story_prompt_content

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
        workspace:str=DEFAULT_WORKSPACE,
    ) -> int | None:
    """ return pid """
    if not msg_or_file:
        return None

    if isinstance(msg_or_file, (list, dict, set)):
        msg_or_file = json_dump(msg_or_file)

    args = ["agent_story", "-m", msg_or_file]
    if model_name:
        args += ["-M", model_name]
    if workspace:
        args += ["-w", workspace]

    return exec_cmd_in_new_process(
        args,
        env=dict(
            PURE_SYSTEM_PROMPT="1",
            STORY_PROMPT=EnvReaderInstance.get("STORY_PROMPT", ""),
            ENABLED_TOOLS="story_tool",
            EXTRA_TOOLS="",
            PLUGIN_TOOLS="",
            DEBUG="0",
        )
    )

def async_agent_memory_as_story(
        msg_or_file,
        model_name:str=None,
        workspace:str=DEFAULT_WORKSPACE,
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


TOOLS = dict(
    WritingAssistant=agent_writer,
    ProgrammingAssistant=agent_programmer,
    WritingAssistantMultiTasks=async_multitasks_agent_writer2,
)

PROMPT = """
## About agent_tool (assistant)
Unless the user explicitly includes the word "assistant" (or phrases such as "call the assistant" or "use an assistant") in their request, you must not invoke, delegate, or imply any third-party assistant/agent_tool to perform the task. All responses must be generated solely by you.
"""
