'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-09
Purpose:
'''

def fix_mistake1(message, **kwargs):
    """
    case:
        BAD:
        {
            "step_name": "action",
            "tool_call": "xxx",
            "arg1": "value1",
            "arg2": "value2"
        }
        GOOD:
        {
            "step_name": "action",
            "tool_call": "xxx",
            "tool_args": {
                "arg1": "value1",
                "arg2": "value2"
            }
        }
    """
    if isinstance(message, list) and len(message) == 1 and isinstance(message[0], dict):
        d = message[0]
        if d.get("step_name") == "action" and \
            d.get("tool_call") and \
            'tool_args' not in d \
        :
            tool_args = {}
            for k, v in d.items():
                if k in ("step_name", "tool_call"):
                    continue
                tool_args[k] = v
            d["tool_args"] = tool_args
            for k in tool_args:
                del d[k]
    return message


MISTAKES = dict(
    fix_mistake1=fix_mistake1,
)
