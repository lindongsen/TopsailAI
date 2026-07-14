'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-13
Purpose: Plan and execute task agent for TopsailAI CLI
'''

import os
import sys

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root + "/src")

os.chdir(project_root)

# init env
os.environ["TOPSAILAI_ENABLED_TOOLS"] = (os.getenv("TOPSAILAI_ENABLED_TOOLS", "+") or "+") + ";" + "subagent_tool;"

# import
from topsailai.tools.subagent_tool import MainAgent

def main():
    MainAgent().run(times=1)

if __name__ == "__main__":
    main()
