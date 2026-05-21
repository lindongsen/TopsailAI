'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-09
Purpose:
'''

import simplejson

from topsailai.utils import (
    format_tool,
)


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
        return simplejson.dumps(d, ensure_ascii=False)
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

def fix_mistake2(message, **_):
    """
    BAD:
    ```
    hello
    <action>
    {
    "tool_call": "file_tool-read_files",
    "tool_args": {
        "files": [
            "/tmp/1.txt"
            ]
        }
    }
    </action>

    GOOD:
    {
        "step_name": "action",
        "raw_text": {
            "tool_call": "file_tool-read_files",
            "tool_args": {
                "files": [
                    "/tmp/1.txt"
                    ]
                }
        }
    }
    ```

    Args:
        message (_type_): _description_
    """
    if isinstance(message, str):
       if '\n<action>\n' in message or message.startswith("<action>\n"):
            new_message1 = message[message.find("<action>\n")+10 : message.find("\n</action>")]
            new_message2 = fix_raw_text(new_message1)
            if new_message2 and new_message2 != new_message1:
                d = {
                    "step_name": "action",
                    "raw_text": new_message2,
                }
                return [d]

    if isinstance(message, list) and len(message) == 1 and isinstance(message[0], dict):
        d = message[0]
        raw_text = d.get("raw_text")
        if raw_text and ('\n<action>\n' in raw_text or raw_text.startswith("<action>\n")):
            new_list = fix_mistake2(raw_text)
            if new_list and isinstance(new_list, list):
                message += new_list
                return message

    return None

MISTAKES = dict(
    fix_mistake1=fix_mistake1,
    fix_mistake2=fix_mistake2,
)
