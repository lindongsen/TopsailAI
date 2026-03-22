#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-26
  Purpose:
'''

import os
import sys
import argparse

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

from topsailai.tools.agent_tool import agent_memory_as_story


def get_params():
    ''' return dict for parameters '''
    parser = argparse.ArgumentParser(
        usage="",
        description=""
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
    params = get_params()
    result = agent_memory_as_story(
        msg_or_file=params["message"],
        model_name=params["model_name"],
        workspace=params["workspace"],
    )
    print(result)

if __name__ == "__main__":
    main()
