'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-18
Purpose:
'''

from topsailai.utils import (
    module_tool,
    print_tool,
)

BASE_PATH = __name__.rsplit('.', 2)[0]

MISTAKES = module_tool.get_function_map(
    BASE_PATH,
    key="MISTAKES",
    need_module_log=False,
)

def check_or_fix_mistakes(response, rsp_obj=None, **kwargs):
    """
    Check or Fix LLM Mistakes

    Args:
        response (list|dict|str): content from LLM
        rsp_obj (any, optional): a object from SDK. Defaults to None.

    Returns: type is same to response
    """
    new_response = response

    for name, func in MISTAKES.items():
        new_response = func(new_response, rsp_obj=rsp_obj, **kwargs)

        if new_response is None:
            continue

        if new_response is response:
            continue

        print_tool.print_error(f"LLM make mistakes (fixed): [{name}], origin=[{response}], new=[{new_response}]")
        break

    return new_response
