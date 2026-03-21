'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

from topsailai.utils import env_tool


HUMAN_STARTSWITH = "Human."


def get_human_name(human_name:str=None) -> str:
    """Get the human name.
    If the human name is not provided, it will be read from the environment variable "TOPSAILAI_HUMAN_NAME".
    If the environment variable is not set, it will default to "DawsonLin".
    The human name will be prefixed with "Human." if it does not already start with it.
    """
    if not human_name:
        human_name = env_tool.EnvReaderInstance.get("TOPSAILAI_HUMAN_NAME")

    if not human_name:
        human_name = "DawsonLin"

    if not human_name.startswith(HUMAN_STARTSWITH):
        human_name = HUMAN_STARTSWITH + human_name

    return human_name
