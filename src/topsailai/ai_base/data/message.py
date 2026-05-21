'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-05-21
Purpose:
'''

class BaseMessageItem(object):
    def __init__(self):
        self.step_name = ""
        self.raw_text = ""


class Message(object):
    def __init__(self, *msg_items:BaseMessageItem):
        self.message = msg_items


class LLMResponseItem(BaseMessageItem):
    """
    step_name can be thought, action, etc.
    raw_text can be str, dict

    if step_name is action, raw_text is json_str or dict, example:
    {
        "tool_call": "TOOL-NAME",
        "tool_args": {
            "arg1": "1",
            "arg2": "2",
        }
    }
    """
    pass


class LLMRequestItem(BaseMessageItem):
    """
    step_name can be task, observation, etc.
    raw_text can be str
    """
    pass
