'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-26
  Purpose:
'''

import os
from dotenv import load_dotenv

from topsailai.workspace import folder_constants

HOME_FOLDER = os.getenv("HOME") or ""

for WORK_FOLDER in [
    os.path.join(HOME_FOLDER, ".topsailai"),
    folder_constants.FOLDER_ROOT,
    os.getcwd(),
]:
    env_file = os.path.join(WORK_FOLDER, ".env")
    if os.path.isdir(WORK_FOLDER) and os.path.exists(env_file):
        os.chdir(WORK_FOLDER)
        os.environ["TOPSAILAI_WORK_FOLDER"] = WORK_FOLDER
        break

# init
os.makedirs(folder_constants.FOLDER_LOG, exist_ok=True)
load_dotenv()
