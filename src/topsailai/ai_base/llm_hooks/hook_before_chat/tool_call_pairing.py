'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-08-28
  Purpose:
    Request-boundary guard for native tool-call pairing.

    Every ``role="tool"`` message must be preceded by an assistant message
    carrying the matching ``tool_calls`` id. Context summarization, session
    truncation and index-based pruning can all break that pairing, and the
    resulting orphaned tool message makes providers reject the whole request
    with errors such as "No tool call found for function call output with
    call_id ...". The failure is sticky because the broken list is resent on
    every retry and every later turn, so the invariant is enforced once at the
    single request chokepoint instead of in each message producer.
'''

from topsailai.logger import logger
from topsailai.utils import message_tool
from topsailai.utils.env_tool import is_use_tool_calls


def hook_execute(content: list) -> list:
    """Drop orphaned tool messages from the outgoing request messages.

    Args:
        content (list): Messages about to be sent to the LLM.

    Returns:
        list: Sanitized messages. The input list is returned unchanged when
        native tool calls are disabled or when sanitization fails.
    """
    if content is None:
        return None

    if not is_use_tool_calls():
        return content

    try:
        return message_tool.drop_orphaned_tool_messages(content, logger)
    except Exception as e:
        logger.exception(e)
    return content
