'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-04
  Purpose: multi-task writing helpers extracted from tools/agent_tool.py.
'''

import os
import threading

from topsailai.logger import logger
from topsailai.utils.json_tool import json_dump, json_load
from topsailai.utils.format_tool import to_list
from topsailai.tools.tool_utils.parameter import resolve_str_param
from topsailai.tools.agent_tool_utils.writer import (
    DEFAULT_WORKSPACE,
    agent_writer,
)


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
    for parameter, value in (
        ("goal", goal),
        ("goal_report_file", goal_report_file),
        ("task_prompt_file", task_prompt_file),
        ("tasks_file_or_json", tasks_file_or_json),
        ("workspace", workspace),
    ):
        _, error = resolve_str_param(value, parameter)
        if error:
            return error
    if model_name is not None:
        model_name, error = resolve_str_param(model_name, "model_name")
        if error:
            return error

    tasks_content = tasks_file_or_json
    if tasks_file_or_json and tasks_file_or_json[0] in ["/", "."]:
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
