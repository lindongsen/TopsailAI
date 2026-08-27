'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

import os

from topsailai.utils.print_tool import (
    PRINT_STEP_MODE_DEFAULT,
    PRINT_STEP_MODE_DESCRIPTIONS,
    PRINT_STEP_MODE_ENV,
    PRINT_STEP_MODE_LIST,
    get_print_step_mode,
)


def set_env(k:str, v:str):
    """set environment

    Args:
        k (str): key
        v (str): value
    """
    k = str(k)
    v = str(v)
    old_v = os.getenv(k)
    if k:
        os.environ[k] = v
    print(f"set environment ok: old={old_v} new={v}")
    return

def get_env(k:str) -> str|None:
    """get environment

    Args:
        k (str): key

    Returns:
        str: value
        None: not config
    """
    return os.getenv(str(k))


def print_step_mode(*args) -> str:
    """
    Show or set TOPSAILAI_PRINT_STEP_MODE (Agent2LLM step console detail).

    Supported forms:
      /print_step_mode            # list supported values, '*' marks the current one
      /print_step_mode <number>   # select by 1-based index
      /print_step_mode <mode>     # select by exact mode name

    Args:
        *args: Positional arguments from the instruction parser.
    """
    choices = list(PRINT_STEP_MODE_LIST)
    current = get_print_step_mode()

    if not args:
        lines = [f"{PRINT_STEP_MODE_ENV} (current: {current}):"]
        for idx, mode in enumerate(choices, start=1):
            marker = "*" if mode == current else " "
            desc = PRINT_STEP_MODE_DESCRIPTIONS.get(mode, "")
            suffix = f"  - {desc}" if desc else ""
            lines.append(f"  {idx}. {marker} {mode}{suffix}")
        lines.append(f"Usage: /print_step_mode <number|mode> (default: {PRINT_STEP_MODE_DEFAULT})")
        return "\n".join(lines)

    arg = str(args[0]).strip()
    if not arg:
        return "Usage: /print_step_mode <number|mode>"

    if arg.isdigit():
        index = int(arg)
        if index < 1 or index > len(choices):
            return f"Invalid index: {index}. Valid range: 1-{len(choices)}"
        mode = choices[index - 1]
    else:
        mode = arg.lower()
        if mode not in choices:
            return f"Invalid mode: {arg}. Valid values: {', '.join(choices)}"

    old_v = os.getenv(PRINT_STEP_MODE_ENV)
    os.environ[PRINT_STEP_MODE_ENV] = mode
    return f"set environment ok: {PRINT_STEP_MODE_ENV} old={old_v} new={mode}"


INSTRUCTIONS = dict(
    set=set_env,
    get=get_env,
    print_step_mode=print_step_mode,
)
