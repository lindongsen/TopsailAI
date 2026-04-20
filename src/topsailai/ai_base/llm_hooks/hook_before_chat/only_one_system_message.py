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
    if not messages:
        return [{"role": ROLE_SYSTEM, "content": ""}]
    
    system_messages = []
    non_system_messages = []
    
    for msg in messages:
        if msg.get("role") == ROLE_SYSTEM:
            system_messages.append(msg)
        else:
            non_system_messages.append(msg)
    
    if len(system_messages) == 0:
        # No system message exists, add a default one
        return [{"role": ROLE_SYSTEM, "content": ""}] + non_system_messages
    
    if len(system_messages) == 1:
        # Only one system message, ensure it's first
        if system_messages[0] not in non_system_messages:
            return system_messages + non_system_messages
        return messages
    
    # Multiple system messages - merge them all
    system_msg_content = "\n\n".join([msg["content"] for msg in system_messages])
    system_msg_item = {
        "role": ROLE_SYSTEM,
        "content": system_msg_content,
    }
    
    merged = [system_msg_item] + non_system_messages
    logger.info("system messages were merged: [%s]", len(system_messages))
    return merged

def hook_execute(content:list) -> list:
    if content is None:
        return None
    try:
        return merge_system_messages(content)
    except Exception as e:
        logger.exception(e)
    return content
