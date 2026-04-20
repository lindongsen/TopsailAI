'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-29
Purpose:
'''

import os
import sys

from topsailai.ai_base.llm_control.base_class import ContentSender
from topsailai.utils import (
    format_tool,
    json_tool,
)
from topsailai.context.chat_history_manager.__base import (
    ChatHistoryMessageData,
)
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


class TeeOutput:
    """ A class that outputs to both the screen and a file simultaneously.

    # Method 1: Using context manager (Recommended, safe)
    with TeeOutput("app.log", mode='w'):
        print("This is a log message")
        print(f"Current time: {datetime.now()}")
        print("Program is running normally...")
        # All prints here will output to both the screen and app.log

    print("This line only outputs to the screen and won't be written to the file")  # Restores normal behavior after exiting 'with'

    # Method 2: Manual setup (Suitable for global logging)
    logger = TeeOutput("runtime.log", mode='a')
    sys.stdout = logger

    print("This will output to both the screen and runtime.log")
    print("Error messages can also be displayed normally")

    # Restore before program ends (Optional)
    # sys.stdout = logger.terminal
    # logger.close()
    """
    def __init__(
            self,
            filename,
            mode='a',
            encoding='utf-8',
            logrotate_max_file_bytes=100 * 1024 * 1024, # default 100 MBytes
        ):
        self.terminal = sys.stdout
        self.filename = filename
        self._logrotate_max_file_bytes = logrotate_max_file_bytes
        self.logrotate_max_file_bytes()
        self.log_file = open(filename, mode, encoding=encoding)

    def logrotate_max_file_bytes(self):
        """Check if the log file exceeds the max size limit and rotate it.

        If the file exists and its size exceeds the configured limit,
        rename the file to "{filename}.1".
        """
        if not os.path.exists(self.filename):
            return

        file_size = os.path.getsize(self.filename)
        if file_size > self._logrotate_max_file_bytes:
            rotated_filename = f"{self.filename}.1"
            os.rename(self.filename, rotated_filename)

    def write(self, message):
        self.terminal.write(message)
        self.log_file.write(message)
        self.flush()

    def flush(self):
        self.terminal.flush()
        self.log_file.flush()

    def close(self):
        self.log_file.close()

    def __enter__(self):
        sys.stdout = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.terminal
        self.close()
        return False


def decorator_tee_output(filename, mode='a', encoding='utf-8', logrotate_max_file_bytes=100 * 1024 * 1024):
    """A function decorator that redirects stdout to both the screen and a file.

    Uses the TeeOutput context manager (with statement) internally.

    Args:
        filename: Path to the log file
        mode: File open mode ('a' for append, 'w' for write)
        encoding: File encoding (default: 'utf-8')
        logrotate_max_file_bytes: Maximum file size in bytes before rotation (default: 100 MB)

    Returns:
        A decorator function

    Example:
        @tee_output("app.log")
        def my_function():
            print("This will be written to both screen and app.log")
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            with TeeOutput(filename, mode, encoding, logrotate_max_file_bytes):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator


def decorator_tee_output_by_session(mode='a+', encoding='utf-8', logrotate_max_file_bytes=100 * 1024 * 1024):
    def decorator(func):
        def wrapper(*args, **kwargs):
            file_path = os.path.join(FOLDER_WORKSPACE_TASK, f"session.stdout")
            session_id = os.getenv("TOPSAILAI_SESSION_ID")
            if session_id:
                file_path = os.path.join(FOLDER_WORKSPACE_TASK, f"{session_id}.session.stdout")
            with TeeOutput(file_path, mode, encoding, logrotate_max_file_bytes):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator


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
