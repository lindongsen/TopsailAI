#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-19
Purpose:
'''

import os
import sys
import argparse

import _import_topsailai

os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)

from topsailai.utils import env_tool
from topsailai.workspace.llm_shell import get_llm_chat


def get_params():
    ''' return dict for parameters '''
    parser = argparse.ArgumentParser(
        usage="",
        description=""
    )
    parser.add_argument(
        "-s", "--session_id", required=True, dest="session_id", type=str,
        default=None,
        help=""
    )
    parser.add_argument(
        "-m", "--message", required=True, dest="message", type=str,
        default=None,
        help=""
    )

    args = parser.parse_args()
    params = {
        "session_id": args.session_id or env_tool.get_session_id(),
        "message": args.message,
    }
    return params

def main():
    params = get_params()
    get_llm_chat(
        session_id=params["session_id"],
        message=params["message"],
    )
    return

if __name__ == "__main__":
    main()
