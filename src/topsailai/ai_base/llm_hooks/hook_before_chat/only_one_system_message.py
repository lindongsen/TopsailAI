'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-26
  Purpose:
'''

from topsailai.logger import logger
from topsailai.ai_base.constants import (
    ROLE_SYSTEM,
)

def merge_system_messages(messages:list):
    system_msg_content = ""
    index = -1
    for i, msg in enumerate(messages):
        if msg["role"] == ROLE_SYSTEM:
            system_msg_content += msg["content"] + "\n\n"
        else:
            break
        index = i

    system_msg_item = {
        "role": ROLE_SYSTEM,
        "content": system_msg_content,
    }
    for _ in range(index+1):
        messages.pop(0)
    messages.insert(0, system_msg_item)
    logger.info("system messages were merged: [%s]", index+1)
    return messages

def hook_execute(content:list) -> list:
    try:
        return merge_system_messages(content)
    except Exception as e:
        logger.exception(e)
    return content
