'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-29
Purpose:
'''

import os
import sys
import time

from topsailai.ai_base.llm_control.content_endpoint import ContentSender
from topsailai.context import token as token_module
from topsailai.utils import (
    format_tool,
    json_tool,
    file_tool,
)
from topsailai.utils.env_tool import (
    EnvReaderInstance,
    get_session_id,
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
            need_delete_log_files=False,
        ):
        self.terminal = sys.stdout
        self.filename = filename
        self._logrotate_file = f"{self.filename}.1"
        self._logrotate_max_file_bytes = logrotate_max_file_bytes
        self.logrotate_max_file_bytes()
        self.log_file = open(filename, mode, encoding=encoding)

        self._need_delete_log_files = need_delete_log_files


    def logrotate_max_file_bytes(self):
        """Check if the log file exceeds the max size limit and rotate it.

        If the file exists and its size exceeds the configured limit,
        rename the file to "{filename}.1".
        """
        if not os.path.exists(self.filename):
            return

        file_size = os.path.getsize(self.filename)
        if file_size > self._logrotate_max_file_bytes:
            rotated_filename = self._logrotate_file
            os.rename(self.filename, rotated_filename)

    def delete_logrotate_file(self):
        file_tool.delete_file(self._logrotate_file)
        return

    def delete_log_files(self):
        file_tool.delete_file(self.filename)
        self.delete_logrotate_file()
        return

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
        if self._need_delete_log_files:
            self.delete_log_files()
        return False

    def __getattr__(self, name):
        return getattr(self.terminal, name)


def decorator_tee_output(
        filename, mode='a', encoding='utf-8', logrotate_max_file_bytes=100 * 1024 * 1024,
        need_delete_log_files=False,
    ):
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
            with TeeOutput(
                    filename, mode, encoding, logrotate_max_file_bytes,
                    need_delete_log_files=need_delete_log_files,
                ):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator


def decorator_tee_output_by_session(
        mode='a+', encoding='utf-8', logrotate_max_file_bytes=100 * 1024 * 1024,
        need_delete_log_files=False,
    ):
    def decorator(func):
        def wrapper(*args, **kwargs):

            if not EnvReaderInstance.check_bool("TOPSAILAI_ENABLE_SESSION_TEE_OUT", False):
                return func(*args, **kwargs)

            pid = os.getpid()
            file_path = os.path.join(FOLDER_WORKSPACE_TASK, f"topsailai.{pid}.session.stdout")
            session_id = get_session_id()
            if session_id:
                file_path = os.path.join(FOLDER_WORKSPACE_TASK, f"{session_id}.{pid}.session.stdout")
            with TeeOutput(
                file_path, mode, encoding, logrotate_max_file_bytes,
                need_delete_log_files=need_delete_log_files,
                ):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator

class ContentDots(ContentSender):
    """
    A content sender implementation that outputs dots for each content sent.

    This class provides a simple visual feedback mechanism by printing dots
    to indicate content transmission progress.

    Kept for backward compatibility; new code should prefer ContentProgress.
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

    def finish(self):
        """
        Emit a final newline so subsequent output is not overwritten.

        Returns:
            bool: Always returns True.
        """
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True


class ContentProgress(ContentSender):
    """
    A content sender that renders streaming LLM progress in a readable way.

    Supported modes (controlled by TOPSAILAI_STREAM_PROGRESS):
      - "dots":  legacy dot-per-chunk behavior for backward compatibility
      - "stats": single-line status with chars/tokens/speed (default)
      - "bar":   compact progress bar with chars/tokens/speed

    The display is refreshed in place with \\r to avoid flooding stdout.
    A final newline is emitted when the stream ends so later logs are not
    overwritten.
    """

    # Default refresh interval in seconds.
    DEFAULT_REFRESH_INTERVAL = 0.1
    # Approximate characters per token for token estimation.
    CHARS_PER_TOKEN = 4.0
    # Progress bar width in characters.
    BAR_WIDTH = 20

    def __init__(self, mode=None, refresh_interval=None, refresh_interval_ms=None):
        """
        Initialize the progress sender.

        Args:
            mode: Display mode ("dots", "stats", or "bar"). When None, the
                value is read from the TOPSAILAI_STREAM_PROGRESS environment
                variable and defaults to "stats".
            refresh_interval: Minimum time in seconds between screen refreshes.
                Defaults to DEFAULT_REFRESH_INTERVAL.
            refresh_interval_ms: Minimum time in milliseconds between screen
                refreshes. Takes precedence over refresh_interval when given.
        """
        if mode is None:
            mode = os.environ.get("TOPSAILAI_STREAM_PROGRESS", "stats").strip().lower()
        if mode not in ("dots", "stats", "bar", ""):
            mode = "stats"
        if mode == "":
            mode = "stats"
        self.mode = mode

        if refresh_interval_ms is not None:
            refresh_interval = refresh_interval_ms / 1000.0
        self.refresh_interval = refresh_interval or self.DEFAULT_REFRESH_INTERVAL

        self._start_time = None
        self._last_refresh_time = 0.0
        self._char_count = 0
        self._token_count = 0
        self._finished = False

    def _estimate_tokens(self, text):
        """Estimate token count from text length."""
        if not text:
            return 0
        return max(1, int(len(text) / self.CHARS_PER_TOKEN))

    def _format_duration(self, seconds):
        """Format elapsed seconds as a compact human-readable string."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m{secs:02d}s"

    def _format_number(self, value):
        """Format a number in compact k/M notation."""
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}k"
        return str(int(value))

    def _should_refresh(self):
        """Return True if enough time has passed since the last refresh."""
        now = time.monotonic()
        return now - self._last_refresh_time >= self.refresh_interval

    def _render_dots(self):
        """Legacy dot-per-chunk output."""
        sys.stdout.write(".")
        sys.stdout.flush()

    def _render_stats(self, elapsed):
        """Render the stats mode status line."""
        speed = self._char_count / elapsed if elapsed > 0 else 0.0
        line = (
            f"\rGenerating... "
            f"{self._format_number(self._char_count)} chars, "
            f"{self._format_number(self._token_count)} tokens, "
            f"{self._format_number(speed)} chars/s, "
            f"{self._format_duration(elapsed)}"
        )
        # Pad with spaces to clear any previous longer line.
        sys.stdout.write(line.ljust(80)[:80])
        sys.stdout.flush()

    def _render_bar(self, elapsed):
        """Render the bar mode status line."""
        speed = self._char_count / elapsed if elapsed > 0 else 0.0
        # Use a rolling pseudo-progress based on chars generated so far.
        # The bar fills up to a soft target and then wraps visually.
        target = max(1000, self._token_count * self.CHARS_PER_TOKEN)
        ratio = min(1.0, self._char_count / target)
        filled = int(self.BAR_WIDTH * ratio)
        bar = "█" * filled + "░" * (self.BAR_WIDTH - filled)
        line = (
            f"\r[{bar}] Generating "
            f"{self._format_number(self._char_count)} chars "
            f"{self._format_number(self._token_count)} tokens "
            f"{self._format_number(speed)} chars/s "
            f"{self._format_duration(elapsed)}"
        )
        sys.stdout.write(line.ljust(80)[:80])
        sys.stdout.flush()

    def send(self, content):
        """
        Update progress with the latest content chunk.

        Args:
            content: The content chunk received from the LLM stream.

        Returns:
            bool: Always returns True to indicate successful handling.
        """
        if content is None:
            content = ""
        text = content if isinstance(content, str) else str(content)

        if self.mode == "dots":
            self._render_dots()
            return True

        now = time.monotonic()
        if self._start_time is None:
            self._start_time = now

        self._char_count += len(text)
        self._token_count += self._estimate_tokens(text)

        if self._should_refresh():
            self._last_refresh_time = now
            elapsed = now - self._start_time
            if self.mode == "bar":
                self._render_bar(elapsed)
            else:
                self._render_stats(elapsed)

        return True

    def finish(self):
        """
        Emit a final newline so subsequent output is not overwritten.

        Returns:
            bool: Always returns True.
        """
        if self._finished:
            return True
        self._finished = True
        sys.stdout.write("\n")
        sys.stdout.flush()
        return True

def _count_words(content):
    """
    Count characters in message content.

    Strings are counted directly with len(). Non-string values are converted
    to str() first, then counted with len(). None counts as 0.
    """
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    return len(str(content))


def _count_tokens(content):
    """
    Count tokens in message content.

    Strings are counted directly using context.token.count_tokens().
    Non-string values are converted to str() first, then counted.
    None counts as 0.
    """
    if content is None:
        return 0
    if not isinstance(content, str):
        content = str(content)
    return token_module.count_tokens(content)


def _truncate_content(content, max_length):
    """
    Truncate content for display without affecting counts.

    Args:
        content: The original message content.
        max_length: Maximum number of characters to display. None means no
            truncation.

    Returns:
        str: The possibly truncated string representation of the content.
    """
    if max_length is None:
        return content
    if content is None:
        return ""
    if not isinstance(content, str):
        content = str(content)
    if max_length <= 0:
        return ""
    if len(content) <= max_length:
        return content
    return content[:max_length] + "..."


def print_context_messages(messages, content_max_length=None):
    """
    Format and print conversation messages for human-readable output

    Args:
        messages: List of message dictionaries containing 'role' and 'content' fields
        content_max_length: Optional maximum number of characters to display
            for each message's content. Does not affect word/token counts.
    """
    for i, msg in enumerate(messages):
        # Get role and content, with default values in case fields are missing
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        create_time = msg.get('create_time', '')

        word_count = _count_words(content)
        token_count = _count_tokens(content)

        # Format the output with visual separators
        print(f"\n{'='*50}")
        print(
            f"#{i+1} - Role: {role.upper()}"
            f" - Words: {word_count}"
            f" - Tokens: {token_count}"
            + (f" - {create_time}" if create_time else "")
        )
        print(f"{'='*50}")

        # Truncate only the displayed content, counts use the original content
        display_content = _truncate_content(content, content_max_length)

        # Handle multiline content while preserving formatting
        try:
            display_content = format_tool.to_topsailai_format(
                display_content, key_name="step_name", value_name="raw_text",
                for_print=True,
            ).strip()
        except Exception:
            pass
        if display_content:
            print(json_tool.safe_json_dump(display_content))
        else:
            print("  [No content]")

    #print(f"\n{'='*50}")
    print()

def print_raw_messages(messages: list[ChatHistoryMessageData]):
    """
    Format and print raw chat history messages for human-readable output.

    Args:
        messages: List of ChatHistoryMessageData objects containing message metadata and content
    """
    for i, msg in enumerate(messages):
        # Parse the message content to get role
        message = msg.message
        content = message
        role = "unknown"
        create_time = ""
        try:
            message = json_tool.json_load(message)
            content = message["content"]
            role = message.get("role", "unknown")
            create_time = message.get("create_time")
        except Exception:
            pass

        # Format the output with visual separators and message_id
        print(f"\n{'='*50}")
        print(
            f"#{i+1} - Role: {role.upper()} - ID: {msg.msg_id}"
            + (f" - ({create_time})" if create_time else "")
        )
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
                print(f"{line}")
        else:
            print("  [No content]")

    print()
