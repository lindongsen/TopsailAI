'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-09
Purpose:
'''

import simplejson

def fix_raw_text(raw_text):
    """
    Return new text

    case1:
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
    d = {}
    if isinstance(raw_text, str):
        try:
            d = simplejson.loads(raw_text)
        except Exception:
            return None
    elif isinstance(raw_text, dict):
        d = raw_text
    if not d:
        return None

    if (
        d.get("tool_call")
        and 'tool_args' not in d
    ):
        tool_args = {}
        for k, v in d.items():
            if k in ("step_name", "tool_call"):
                continue
            tool_args[k] = v
        d["tool_args"] = tool_args
        for k in tool_args:
            del d[k]

    if isinstance(raw_text, dict):
        return d
    elif isinstance(raw_text, str):
        return simplejson.dumps(raw_text, ensure_ascii=False)
    return None

def fix_mistake1(message, **kwargs):
    """
    case1:
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

    case2:
        BAD:
        {
            "step_name": "action",
            "raw_text": {
                "tool_call": "xxx",
                "arg1": "value1",
                "arg2": "value2"
            }
        }
        GOOD:
        {
            "step_name": "action",
            "raw_text": {
                "tool_call": "xxx",
                "tool_args": {
                    "arg1": "value1",
                    "arg2": "value2"
                }
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

        raw_text = d.get("raw_text")
        if (
            d.get("step_name") == "action"
            and raw_text
        ):
            new_raw_text = fix_raw_text(raw_text)
            if new_raw_text:
                d["raw_text"] = new_raw_text

    return message


MISTAKES = dict(
    fix_mistake1=fix_mistake1,
)
