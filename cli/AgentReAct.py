#!/usr/bin/env python
# encoding: utf-8

# this is a ai agent, it running in ReAct framework.
# it can think, act, observe and give final answer.
# it can use tool exec_cmd to execute command line in local system.

import os
import sys
# DONOT DELETE THIS FOR FUNCTION 'input'
import readline
import argparse
from dotenv import load_dotenv

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.utils.print_tool import (
    enable_flag_print_step,
    disable_flag_print_step,
)
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.ai_base.agent_types.react import (
    Step4ReAct,
)

from topsailai.workspace.agent_shell import get_agent_chat as get_agent


# define global variables
g_flag_interactive = True


def run_once(user_input, to_print_step=None, user_prompt=""):
    """ return final answer, or None if error """
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
    step_call = Step4ReAct(flag_interactive=g_flag_interactive)
    final_answer = agent.run(step_call, user_input)
    return final_answer

def continue_task(msg_file):
    """ continue a task """
    agent = get_agent()
    agent.load_messages(msg_file)
    final_answer = agent.run(Step4ReAct(), "")
    return final_answer

def get_params():
    ''' return dict for parameters '''
    parser = argparse.ArgumentParser(
        usage="",
        description=""
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
        with open(params["prompt_file"], "r") as fd:
            params["prompt_content"] = fd.read() or ""

    # set flags
    if params["flag_dump_messages"]:
        PromptBase.flag_dump_messages = True

    return params


def main():
    """ return nothing """
    load_dotenv()  # load environment variables from .env file if present

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
    print("Welcome to the AI Agent Shell. Type 'exit' to quit.")
    while True:
        user_input = input("\n>>> Enter your task: ")
        if user_input.lower() in ['exit', 'quit']:
            break
        if user_input.strip() == "":
            continue
        final_answer = agent.run(Step4ReAct(), user_input)
        if final_answer:
            print(f"\nFinal Answer: {final_answer}")
        else:
            print("Failed to get a final answer.")
    return

if __name__ == "__main__":
    main()
