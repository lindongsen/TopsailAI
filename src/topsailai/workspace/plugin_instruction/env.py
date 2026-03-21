'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-21
  Purpose:
'''

import os

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


INSTRUCTIONS = dict(
    set=set_env,
    get=get_env,
)
