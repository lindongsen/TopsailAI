'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-29
  Purpose:
'''

from topsailai.logger import logger
from .tool_utils.parameter import resolve_str_param
from topsailai.utils.env_tool import is_archive_message_enabled, is_use_tool_calls
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
    msg_id, error = resolve_str_param(msg_id, "msg_id")
    if error:
        return error

    # When native tool calls are enabled, context archiving is disabled, so
    # there is never any archived message to retrieve. Short-circuit here to
    # avoid a pointless lookup and a misleading error log.
    if is_use_tool_calls():
        logger.warning("retrieve_msg is unavailable because native tool calls are enabled")
        return ""

    if not is_archive_message_enabled():
        logger.warning("retrieve_msg is unavailable because archive messages are disabled")
        return ""

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


# Context archiving (which produces retrievable messages) is disabled under
# native tool calls or when the archive-message switch is off, so hide this
# tool from the registry in either mode.
FLAG_TOOL_ENABLED = not is_use_tool_calls() and is_archive_message_enabled()


TOOLS = dict(
    retrieve_msg=retrieve_msg,
)
