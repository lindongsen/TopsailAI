'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose:
'''

from topsailai.logger import logger
from topsailai.utils.thread_local_tool import (
    get_agent_object,
)

def retrieve_msg(msg_id:str):
    """
    When you see the `raw_text` has msg_id=xxx and `step_name` is "archive", it means this message has been archived.
    If you need this message, call this tool to retrieve the message.

    Args:
        msg_id (str):
    """
    agent = get_agent_object()
    if agent is None:
        logger.error("no found agent object")
        return ""

    for mgr in agent.hooks_ctx_history:
        content = mgr.retrieve_message(msg_id)
        if content:
            return content
    # end for

    logger.error(f"failed to retrieve this message: [{msg_id}]")
    return ""


TOOLS = dict(
    retrieve_msg=retrieve_msg,
)
