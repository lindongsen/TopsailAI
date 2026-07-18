'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-13
Purpose: Plan and execute task agents for TopsailAI CLI
'''

import argparse
import os
import sys

import _import_topsailai

os.chdir(_import_topsailai.PROJECT_FOLDER_BASE)

# init env
os.environ["TOPSAILAI_ENABLED_TOOLS"] = (os.getenv("TOPSAILAI_ENABLED_TOOLS", "+") or "+") + ";" + "subagent_tool;"

# import
from topsailai.tools.subagent_tool import MainAgent


def main():
    parser = argparse.ArgumentParser(
        description="Plan and execute task agents for TopsailAI CLI."
    )
    parser.add_argument(
        "message",
        nargs="*",
        help="Optional arguments accepted for backward compatibility; they are parsed but not forwarded."
    )
    parser.parse_args()
    MainAgent().run()


if __name__ == "__main__":
    main()
