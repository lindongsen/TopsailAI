'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-22
  Purpose: Token counting and statistics utilities for LLM interactions

  This module provides utilities for token counting and statistics tracking
  in Large Language Model (LLM) interactions. It includes functions for
  counting tokens in text and a thread-based statistics tracker for
  monitoring token usage over time.
'''

import time
import threading

import tiktoken

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import print_step


def count_tokens(text, encoding_name="cl100k_base"):
    """
    Count the number of tokens in the given text using the specified encoding.

    This function uses the tiktoken library to encode text and count tokens,
    which is essential for managing LLM API costs and context window limits.

    Args:
        text (str): The text to count tokens for. Can be any string content.
        encoding_name (str): The encoding name to use. Defaults to "cl100k_base"
                           which is commonly used for GPT-4 and newer models.

    Returns:
        int: The number of tokens in the text. Returns 0 if encoding fails.

    Raises:
        Exception: Propagates any exceptions from tiktoken encoding,
                  but catches them and returns 0 with a warning log.

    Example:
        >>> count_tokens("Hello world")
        2
        >>> count_tokens("Hello world", "gpt2")
        3
    """
    try:
        # Get the encoding object for the specified encoding name
        encoding = tiktoken.get_encoding(encoding_name)

        # Encode the text into tokens and count the length
        tokens = encoding.encode(text)
        return len(tokens)

    except Exception as e:
        # Log warning and return 0 if token counting fails
        logger.warning(f"failed to count tokens: {e}")
        return 0


def count_tokens_for_model(text, model_name="gpt-4"):
    """
    Count tokens for a specific model using its default encoding.

    This function automatically selects the appropriate encoding for the
    specified model, making it convenient for model-specific token counting.

    Args:
        text (str): The text to count tokens for.
        model_name (str): The model name to get encoding for.
                         Defaults to "gpt-4".

    Returns:
        int: The number of tokens in the text. Returns 0 if encoding fails.

    Raises:
        Exception: Propagates any exceptions from tiktoken encoding,
                  but catches them and returns 0 with a warning log.

    Example:
        >>> count_tokens_for_model("Hello world", "gpt-4")
        2
        >>> count_tokens_for_model("Hello world", "gpt-3.5-turbo")
        2
    """
    try:
        # Get the encoding specifically designed for the model
        encoding = tiktoken.encoding_for_model(model_name)

        # Encode the text and count the resulting tokens
        tokens = encoding.encode(text)
        return len(tokens)

    except Exception as e:
        # Log warning and return 0 if model-specific encoding fails
        logger.warning(f"failed to count tokens: {e}")
        return 0


class TokenStat(threading.Thread):
    """
    Token statistics thread class for tracking token usage in LLM interactions.

    This class runs as a background thread to monitor and accumulate token counts
    and text lengths for messages sent to LLMs. It's particularly useful for:
    - Monitoring API usage and costs
    - Tracking conversation complexity
    - Managing context window limits
    - Performance monitoring and optimization

    The thread automatically manages its lifecycle based on configured lifetime
    and idle time, ensuring efficient resource usage.

    Attributes:
        total_count (int): Total accumulated token count across all messages
        current_count (int): Token count for the most recent message
        total_text_len (int): Total accumulated text length in characters
        current_text_len (int): Text length for the most recent message
        msg_count (int): Number of messages processed
        _start_time (int): Timestamp when the thread was started
        _end_time (int): Timestamp when the thread should end (0 for infinite)
        _last_msg_time (int): Timestamp of the last message processed
        buffer: Temporary storage for incoming messages
        rlock (threading.RLock): Reentrant lock for thread-safe operations
        flag_running (bool): Control flag for thread execution
    """

    def __init__(self, llm_id: str, lifetime: int = 86400):
        """
        Initialize the TokenStat thread.

        Sets up the thread with proper naming, timing controls, and initializes
        all statistical counters to zero.

        Args:
            llm_id (str): LLM identifier used for thread naming and logging.
                         Helps distinguish between multiple LLM instances.
            lifetime (int): Thread lifetime in seconds.
                          - Values <= 0: Run forever (infinite lifetime)
                          - Values > 0: Run for specified seconds plus 60s buffer
                          Defaults to 86400 seconds (24 hours).

        Note:
            The thread is started automatically upon initialization as a daemon thread.
        """
        # Initialize timing controls
        self._start_time = int(time.time())
        self._end_time = 0
        if lifetime > 0:
            # Add 60 seconds buffer to the specified lifetime
            self._end_time = self._start_time + lifetime + 60
        self._last_msg_time = 0

        # Initialize parent thread class with daemon flag and descriptive name
        super(TokenStat, self).__init__(name=f"TokenStat:{llm_id}", daemon=1)

        # Initialize statistical counters
        self.total_count = 0        # Total tokens across all messages
        self.current_count = 0      # Tokens in current/last message

        self.total_text_len = 0     # Total characters across all messages
        self.current_text_len = 0   # Characters in current/last message

        self.msg_count = 0          # Number of messages processed

        # Thread synchronization and data management
        self.buffer = None          # Temporary message storage
        self.rlock = threading.RLock()  # Reentrant lock for thread safety

        self.flag_running = True    # Control flag for thread execution

        # Start the thread automatically
        self.start()

    def output_token_stat(self):
        """
        Output current token statistics to the log.

        This method provides a snapshot of current statistics including:
        - Total and current token counts
        - Total and current text lengths
        - Message count

        The output is logged both through the print_step utility and the logger
        for visibility in different output streams.

        Returns:
            None
        """
        # Use lock to ensure thread-safe access to statistics
        with self.rlock:
            info = dict(
                total_count=self.total_count,
                current_count=self.current_count,
                total_text_len=self.total_text_len,
                current_text_len=self.current_text_len,
                msg_count=self.msg_count,
            )

        # Format and output the statistics
        msg = f"[token_stat] {info}"
        print_step(msg, need_format=False)      # Output to console/step display
        logger.info(msg)     # Output to log file
        return

    def add_msgs(self, msgs):
        """
        Add messages to the buffer for token calculation.

        This method places messages in the buffer for asynchronous processing
        by the thread. The actual token counting happens in the background thread.

        Args:
            msgs: Messages to be sent to the LLM. Can be:
                 - A list of messages (for multi-message interactions)
                 - A single string message
                 - Any object that can be converted to string

        Returns:
            None

        Note:
            The method updates the last message timestamp and resets current
            counters to prepare for new message processing.
        """
        # Use lock for thread-safe buffer operations
        with self.rlock:
            # Store messages in buffer for background processing
            self.buffer = msgs

            # Update message count and reset current counters
            self.msg_count = len(msgs)
            self.current_count = 0
            self.current_text_len = 0

            # Update timestamp for last message activity
            self._last_msg_time = int(time.time())

    def run(self):
        """
        Main thread loop for processing token statistics.

        This method runs in a separate thread and continuously monitors
        the buffer for new messages to process. It handles:
        - Token counting for incoming messages
        - Thread lifecycle management based on lifetime and idle time
        - Resource cleanup and graceful shutdown

        The loop runs with a 10ms sleep interval to balance responsiveness
        and CPU usage efficiency.
        """
        # Set running flag to indicate thread is active
        self.flag_running = True

        # Control frequency for lifetime checks
        count_freq = 0
        need_freq = False
        if self._end_time:
            need_freq = True

        # Maximum idle time before considering shutdown (10 minutes)
        max_idle_time = 600

        def check():
            """
            Check if the thread should continue running.

            This internal function evaluates thread termination conditions:
            - If lifetime has been reached and sufficient idle time has passed
            - If the thread should continue processing

            Returns:
                bool: True if thread should continue, False if it should stop
            """
            # Check if lifetime limit has been configured
            if self._end_time:
                now_ts = int(time.time())
                # Check if current time exceeds end time
                if self._end_time < now_ts:
                    # Additional check: ensure sufficient idle time has passed
                    if now_ts - self._last_msg_time > max_idle_time:
                        logger.info("quit due to lifetime is reached")
                        return False
                    # If LLM might still be in use, continue running
                    # This handles cases where tools are still processing

            return True

        # Main thread execution loop
        while self.flag_running:
            # Perform lifetime check periodically if needed
            if need_freq:
                count_freq += 1
                # Check every 10 seconds (1000 iterations * 0.01 sleep)
                if count_freq > 1000:
                    count_freq = 0
                    if not check():
                        break

            # Short sleep to prevent excessive CPU usage
            time.sleep(0.01)

            # Check if there are messages in the buffer to process
            buffer = self.buffer
            if not buffer:
                continue

            # Process the buffered messages
            with self.rlock:
                # Clear the buffer to indicate processing has started
                self.buffer = None

                # Convert messages to string for token counting
                if not isinstance(buffer, str):
                    buffer = str(buffer)

                # Calculate text length and token count
                self.current_text_len = len(buffer)
                self.current_count = count_tokens(buffer)

                # Update cumulative statistics
                self.total_count += self.current_count
                self.total_text_len += self.current_text_len

        # Thread cleanup and exit logging
        logger.info(f"TokenStat is exited: {self.name}")