'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose: Message truncation utilities for managing message size limits in different agent contexts
'''

from topsailai.utils import print_tool
from topsailai.utils.thread_local_tool import get_agent_name

# Maximum message size for most agents
MAX_MSG_SIZE = 3000
# Larger message size threshold for AgentWriter
LARGE_MSG_SIZE = 13000


def is_need_truncate(msg_len: int) -> bool:
    """
    Determine if a message needs to be truncated based on its length and agent type.
    
    Args:
        msg_len (int): The length of the message to check
        
    Returns:
        bool: True if the message needs truncation, False otherwise
        
    Note:
        - AgentWriter has a higher threshold (LARGE_MSG_SIZE) than other agents (MAX_MSG_SIZE)
        - This allows AgentWriter to handle larger content while maintaining size limits for other agents
    """
    # Get the current agent name from thread-local storage
    agent_name = get_agent_name()
    
    # Special handling for AgentWriter with higher size limit
    if agent_name == "AgentWriter":
        # Only truncate if message exceeds the large message size limit
        if msg_len > LARGE_MSG_SIZE:
            return True
        return False
    
    # For all other agents, use the standard maximum message size
    if msg_len >= MAX_MSG_SIZE:
        return True
    
    return False


def truncate_message(msg) -> str | bytes:
    """
    Truncate a message to the maximum allowed size with appropriate suffix.
    
    Args:
        msg (str | bytes): The message to truncate, can be string or bytes
        
    Returns:
        str | bytes: The truncated message with suffix if truncated
        
    Note:
        - If the message is truncated, a suffix " ... (force to truncate)" is added
        - The function handles both string and bytes input types
        - A warning message is printed when truncation occurs
    """
    suffix = ""
    
    # Check if truncation is needed based on message length
    if is_need_truncate(len(msg)):
        # Print error message indicating truncation
        print_tool.print_error(f"truncate message with the size: [{MAX_MSG_SIZE}]")
        # Set truncation suffix
        suffix = " ... (force to truncate)"

    # Handle bytes type message
    if isinstance(msg, bytes):
        if suffix:
            # Convert string suffix to bytes for consistency
            suffix = bytes(suffix, "utf-8")
        else:
            suffix = b""
    
    # Return truncated message (first MAX_MSG_SIZE characters) plus suffix
    return msg[:MAX_MSG_SIZE] + suffix