#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-17
Purpose:
'''

import sys
import os
import argparse

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if os.path.exists(project_root + "/src"):
    project_root += "/src"
sys.path.insert(0, project_root)

os.chdir(project_root)

from topsailai.workspace.agent_shell import get_agent_chat


def get_params():
    ''' return dict for parameters '''
    parser = argparse.ArgumentParser(
        usage="",
        description=""
    )
    parser.add_argument(
        "-i", "--instruction", required=True, dest="instruction", type=str,
        default=None,
        help="/help to show all instuctions"
    )
    parser.add_argument(
        "-p", "--parameters", required=False, dest="parameters", type=str,
        default=None,
        help="str split by ' ' or json_str"
    )
    args = parser.parse_args()
    params = {
        "instruction": args.instruction,
        "parameters": args.parameters,
    }
    if params["instruction"][0] != '/':
        params["instruction"] = "/" + params["instruction"]
    return params

def main():
    """
    Main entry point for single-turn agent chat.

    This function creates and runs a single-turn chat session with an AI agent.
    The agent has access to various tools but the "agent_tool" is disabled
    to prevent recursive agent calls.

    The function:
    1. Gets an agent chat instance with agent_tool disabled
    2. Runs the chat for exactly one iteration (single-turn)
    3. Returns the agent's response

    Returns:
        None: The agent's response is printed to stdout during execution

    Note:
        - This is a single-turn chat (times=1)
        - The agent_tool is disabled to prevent nested agent calls
        - Session history can be maintained via SESSION_ID environment variable
    """
    params = get_params()
    get_agent_chat(need_input_message=False).hook_instruction.call_hook(hook_name=params["instruction"], kwargs=params["parameters"])

if __name__ == "__main__":
    main()
