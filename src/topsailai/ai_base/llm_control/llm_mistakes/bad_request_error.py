'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-18
Purpose:
'''

from ..exception import ModelServiceError


def check_mistake1(message, **kwargs):
    """
    Case:
        [
            {
                "error": {
                "message": "Unterminated string starting at: line 1 column 83 (char 82)",
                "type": "BadRequestError",
                "param": null,
                "code": 400
                }
            }
        ]
    """
    if isinstance(message, list) and len(message) == 1 and isinstance(message[0], dict):
        d = message[0]
        if "error" in d and isinstance(d["error"], dict):
            if d.get("type") == "BadRequestError":
                raise ModelServiceError(d)

    return None


MISTAKES = dict(
    check_mistake1=check_mistake1,
)
