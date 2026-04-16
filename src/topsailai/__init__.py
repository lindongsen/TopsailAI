'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-03-26
Purpose:
'''

import os
from dotenv import load_dotenv

# Original Environ
_env_topsailai_use_tool_calls = os.getenv("TOPSAILAI_USE_TOOL_CALLS")

from topsailai.logger import logger
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
        os.environ["PWD"] = WORK_FOLDER
        load_dotenv(env_file)
        break

def customize_for_llm():
    """ Customize according to the large model """

    # case: TOPSAILAI_USE_TOOL_CALLS
    if _env_topsailai_use_tool_calls is None:
        model_name = os.getenv("OPENAI_MODEL", "").lower()
        for _key in [
            "minimax",
        ]:
            if not model_name:
                break

            if model_name.startswith(_key):
                os.environ["TOPSAILAI_USE_TOOL_CALLS"] = "1"
                logger.warning("Force to set TOPSAILAI_USE_TOOL_CALLS=1 due to LLM Model is [%s]", model_name)

    return

def init_after_loading_dotenv():
    """ Init something """
    customize_for_llm()

# init
os.makedirs(folder_constants.FOLDER_LOG, exist_ok=True)
load_dotenv()

init_after_loading_dotenv()
