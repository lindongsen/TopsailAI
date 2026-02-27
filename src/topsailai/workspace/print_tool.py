'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-29
Purpose:
'''

import sys

from topsailai.ai_base.llm_control.base_class import ContentSender
from topsailai.utils import (
    format_tool,
    json_tool,
)
from topsailai.context.chat_history_manager.__base import (
    ChatHistoryMessageData,
)


class ContentDots(ContentSender):
    """
    A content sender implementation that outputs dots for each content sent.

    This class provides a simple visual feedback mechanism by printing dots
    to indicate content transmission progress.
    """

    def send(self, content):
        """
        Send content by printing a dot character.

        Args:
            content: The content to be sent (not used in this implementation)

        Returns:
            bool: Always returns True to indicate successful transmission
        """
        sys.stdout.write(".")
        sys.stdout.flush()
        return True

def print_context_messages(messages):
    """
    Format and print conversation messages for human-readable output

    Args:
        messages: List of message dictionaries containing 'role' and 'content' fields
    """
    for i, msg in enumerate(messages):
        # Get role and content, with default values in case fields are missing
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')

        # Format the output with visual separators
        print(f"\n{'='*50}")
        print(f"#{i+1} - Role: {role.upper()}")
        print(f"{'='*50}")

        # Handle multiline content while preserving formatting
        try:
            content = format_tool.to_topsailai_format(
                content, key_name="step_name", value_name="raw_text",
                for_print=True,
            ).strip()
        except Exception:
            pass
        if content:
            lines = content.split('\n')
            for line in lines:
                print(f"  {line}")
        else:
            print("  [No content]")

    #print(f"\n{'='*50}")

def print_raw_messages(messages: list[ChatHistoryMessageData]):
    """
    Format and print raw chat history messages for human-readable output.

    Args:
        messages: List of ChatHistoryMessageData objects containing message metadata and content
    """
    for i, msg in enumerate(messages):
        # Parse the message content to get role
        content = msg.message
        role = "unknown"
        try:
            msg_dict = json_tool.json_load(content)
            role = msg_dict.get("role", "unknown")
        except Exception:
            pass

        # Format the output with visual separators and message_id
        print(f"\n{'='*50}")
        print(f"#{i+1} - Role: {role.upper()} - ID: {msg.msg_id}")
        print(f"{'='*50}")

        # Handle multiline content while preserving formatting
        try:
            content = format_tool.to_topsailai_format(
                content, key_name="step_name", value_name="raw_text",
                for_print=True,
            ).strip()
        except Exception:
            pass
        if content:
            lines = content.split('\n')
            for line in lines:
                print(f"  {line}")
        else:
            print("  [No content]")
