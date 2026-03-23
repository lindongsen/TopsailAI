#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Agent Story CLI - Convert agent memory to a story format

This module provides command-line functionality to transform agent memory
or messages into a coherent story format using an LLM. It processes the
input message and generates a narrative-style output.

Usage:
    agent_story.py -m <message> [-M model_name] [-w workspace]

Arguments:
    -m, --message:    Required. The message or task to convert to story format.
                      Use '-' to read from stdin.
    -M, --model_name: Optional. LLM model name to use for generation.
    -w, --workspace:  Optional. Workspace folder path for file operations.

Examples:
    agent_story.py -m "Summarize the meeting about project X"
    echo "Task description" | agent_story.py -m -
    agent_story.py -m "Create a story from memory" -M gpt-4 -w /path/to/workspace

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-26
"""

import os
import sys
import argparse

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.tools.agent_tool import agent_memory_as_story


def get_params():
    """
    Parse command-line arguments and return parameters as a dictionary.
    
    This function uses argparse to parse the following arguments:
    - message: Required message or task to convert to story format
    - model_name: Optional LLM model name
    - workspace: Optional workspace folder path
    
    Returns:
        dict: Dictionary containing parsed parameters:
              - message (str): The input message or task
              - model_name (str or None): LLM model name
              - workspace (str or None): Workspace folder path
              
    Raises:
        SystemExit: Exits with error if required message argument is missing
        AssertionError: If message is empty after parsing
        
    Note:
        If message is '-', content is read from stdin
    """
    parser = argparse.ArgumentParser(
        usage="",
        description="Convert agent memory to story format using LLM"
    )
    parser.add_argument(
        "-m", "--message", required=True, dest="message", type=str,
        default=None,
        help="if give '-', read content from stdin "
    )
    parser.add_argument(
        "-M", "--model_name", required=False, dest="model_name", type=str,
        default=None,
        help="LLM"
    )
    parser.add_argument(
        "-w", "--workspace", required=False, dest="workspace", type=str,
        default=None,
        help="folder path"
    )

    args = parser.parse_args()
    params = {
        "message": args.message,
        "model_name": args.model_name,
        "workspace": args.workspace,
    }

    if params["message"] == "-":
        with open("/dev/stdin", encoding="utf-8") as fd:
            params["message"] = fd.read()

    # check
    assert params["message"], "missing message"

    return params


def main():
    """
    Main entry point for converting agent memory to story format.
    
    This function:
    1. Parses command-line arguments using get_params()
    2. Calls agent_memory_as_story() to transform the message into a story
    3. Prints the resulting story output
    
    The function uses the agent_memory_as_story tool which leverages an LLM
    to convert the input message/task into a coherent narrative format.
    
    Returns:
        None
        
    Example:
        $ python agent_story.py -m "Meeting about project launch"
        The team gathered to discuss the upcoming project launch...
    """
    params = get_params()
    result = agent_memory_as_story(
        msg_or_file=params["message"],
        model_name=params["model_name"],
        workspace=params["workspace"],
    )
    print(result)


if __name__ == "__main__":
    main()
