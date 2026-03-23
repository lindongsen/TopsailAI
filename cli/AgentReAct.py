#!/usr/bin/env python
# encoding: utf-8
"""
AgentReAct CLI - AI Agent running in ReAct (Reasoning + Acting) framework

This module provides an AI agent that operates using the ReAct framework,
which enables the agent to think, act, observe, and provide final answers.
The agent can use various tools including command execution to perform tasks.

The ReAct (Reasoning + Acting) approach combines:
- Reasoning: The agent thinks about the current state and decides on actions
- Acting: The agent executes actions (e.g., running commands, using tools)
- Observing: The agent observes the results of actions
- Final Answer: The agent provides a final response after reasoning

Usage:
    AgentReAct.py [options]

Options:
    -p, --prompt_file FILE    Give a prompt file to extend system prompt
    -t, --task TASK           Give a task for run-once mode
    --dump_msg                Dump all messages to a file
    --msg_file FILE           Use the msg_file to continue a task

Examples:
    AgentReAct.py -t "List all files in current directory"
    AgentReAct.py -p custom_prompt.txt
    AgentReAct.py --msg_file previous_session.json
    AgentReAct.py --dump_msg -t "Your task here"

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import os
import sys
import argparse

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.utils.print_tool import (
    enable_flag_print_step,
    disable_flag_print_step,
)
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.workspace.agent_shell import get_agent_chat


# define global variables
g_flag_interactive = True


def get_agent(system_prompt="", to_dump_messages=False, disabled_tools:list[str]=None):
    """
    Create and return an agent chat instance configured for ReAct mode.
    
    This function creates an agent that uses the ReAct (Reasoning + Acting)
    framework for task execution. The agent can think, act, observe, and
    provide final answers.
    
    Args:
        system_prompt (str, optional): System prompt to configure the agent's
                                       behavior and capabilities. Defaults to "".
        to_dump_messages (bool, optional): Whether to dump all messages to a
                                           file for debugging. Defaults to False.
        disabled_tools (list[str], optional): List of tool names to disable.
                                              Defaults to None.
    
    Returns:
        AgentChat: An agent chat instance configured with ReAct agent type.
        
    Example:
        >>> agent = get_agent(system_prompt="You are a helpful assistant")
        >>> type(agent).__name__
        'AgentChat'
    """
    return get_agent_chat(
        system_prompt=system_prompt,
        to_dump_messages=to_dump_messages,
        disabled_tools=disabled_tools,
        agent_type="react"
    )


def run_once(user_input, to_print_step=None, user_prompt=""):
    """
    Execute a single task in non-interactive mode using the ReAct agent.
    
    This function runs the agent once with the given user input and returns
    the final answer. It's designed for batch processing or single-task execution.
    
    Args:
        user_input (str): The task or question to be processed by the agent.
                          This is a required parameter.
        to_print_step (bool, optional): Whether to enable step-by-step printing
                                        of the agent's reasoning process.
                                        - True: Enable detailed step printing
                                        - False: Disable step printing
                                        - None: Keep current setting
        user_prompt (str, optional): Additional user prompt to extend the system
                                     prompt. Defaults to "".
    
    Returns:
        str or None: The final answer from the agent, or None if an error occurred.
        
    Raises:
        AssertionError: If user_input is empty or None
        
    Example:
        >>> result = run_once("What is the current directory?")
        >>> print(result)
        The current working directory is /home/user
    """
    assert user_input, "user_input is required"
    if to_print_step:
        enable_flag_print_step()
    elif to_print_step is False:
        disable_flag_print_step()

    global g_flag_interactive
    g_flag_interactive = False
    if os.getenv("INTERACTIVE") == "1":
        g_flag_interactive = True

    agent = get_agent(user_prompt)
    final_answer = agent.run(
        message=user_input, times=1,
        need_interactive=g_flag_interactive,
    )
    return final_answer


def continue_task(msg_file):
    """
    Continue a previously saved task from a message file.
    
    This function loads a previously saved session (messages) from a file
    and continues the task from where it left off.
    
    Args:
        msg_file (str): Path to the file containing saved messages from a
                        previous session.
    
    Returns:
        str or None: The final answer from continuing the task, or None if failed.
        
    Example:
        >>> result = continue_task("/tmp/previous_session.json")
        >>> print(result)
        Continuing from previous task...
    """
    agent = get_agent()
    agent.ai_agent.load_messages(msg_file)
    final_answer = agent.run(message="", times=1)
    return final_answer


def get_params():
    """
    Parse command-line arguments and return parameters as a dictionary.
    
    This function uses argparse to parse the following arguments:
    - prompt_file: Optional path to a file containing additional system prompt
    - task: Optional task to execute in run-once mode
    - flag_dump_messages: Whether to dump all messages to a file
    - msg_file: Optional path to a file containing previous session messages
    
    Returns:
        dict: Dictionary containing parsed parameters:
              - prompt_file (str or None): Path to prompt file
              - prompt_content (str): Content of the prompt file
              - task (str or None): Task to execute
              - flag_dump_messages (bool): Whether to dump messages
              - msg_file (str or None): Path to message file for continuing task
              
    Example:
        >>> params = get_params()
        >>> print(params)
        {'prompt_file': None, 'prompt_content': '', 'task': None, ...}
    """
    parser = argparse.ArgumentParser(
        usage="",
        description="AI Agent running in ReAct framework"
    )
    parser.add_argument(
        "-p", "--prompt_file", required=False, dest="prompt_file", type=str,
        default=None,
        help="give a prompt file to extend system prompt"
    )
    parser.add_argument(
        "-t", "--task", required=False, dest="task", type=str,
        default=None,
        help="give a task for runonce mode"
    )
    parser.add_argument(
        "--dump_msg", action="store_true", required=False, dest="flag_dump_messages",
        default=False,
        help="dump all of messages to a file"
    )
    parser.add_argument(
        "--msg_file", required=False, dest="msg_file", type=str,
        default=None,
        help="use the msg_file to continue a task"
    )
    args = parser.parse_args()
    params = {
        "prompt_file": args.prompt_file,
        "prompt_content": "",
        "task": args.task,
        "flag_dump_messages": args.flag_dump_messages,
        "msg_file": args.msg_file,
    }

    # get prompt content
    if params["prompt_file"]:
        with open(params["prompt_file"], "r", encoding='utf-8') as fd:
            params["prompt_content"] = fd.read() or ""

    # set flags
    if params["flag_dump_messages"]:
        PromptBase.flag_dump_messages = True

    return params


def main():
    """
    Main entry point for the AgentReAct CLI.
    
    This function supports three modes of operation:
    1. Continue mode: Load a previous session from msg_file and continue the task
    2. Run-once mode: Execute a single task provided via -t/--task argument
    3. Interactive mode: Start an interactive chat session (default)
    
    The function parses command-line arguments and executes the appropriate
    mode based on the provided arguments.
    
    Returns:
        None
        
    Mode Details:
        - Continue mode: If --msg_file is provided, loads previous session
                        and continues the task
        - Run-once mode: If -t/--task is provided, executes the task once
                        and prints the final answer
        - Interactive mode: Default mode, starts an interactive chat session
        
    Example:
        $ python AgentReAct.py -t "List files"
        >>> Final Answer:
        ['file1.txt', 'file2.txt', ...]
    """
    params = get_params()

    # continue a task
    if params["msg_file"]:
        final_answer = continue_task(params["msg_file"])
        if final_answer:
            print(f"\n>>> Final Answer:\n{final_answer}")
        else:
            print("Failed to get a final answer.")
        return

    # run once mode
    if params["task"]:
        final_answer = run_once(
            user_input=params["task"],
            user_prompt=params["prompt_content"]
        )
        if final_answer:
            print(f"\n>>> Final Answer:\n{final_answer}")
        else:
            print("Failed to get a final answer.")
        return

    # interactive mode
    agent = get_agent(params["prompt_content"])
    agent.run()

    return


if __name__ == "__main__":
    main()
