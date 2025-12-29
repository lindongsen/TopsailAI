'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-22
  Purpose: Token counting and statistics utilities for LLM interactions
'''

import time
import threading

import tiktoken

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import print_step


def count_tokens(text, encoding_name="cl100k_base"):
    """
    Count the number of tokens in the given text using the specified encoding.

    Args:
        text (str): The text to count tokens for
        encoding_name (str): The encoding name to use, defaults to "cl100k_base"

    Returns:
        int: The number of tokens in the text

    Example:
        >>> count_tokens("Hello world")
        2
    """
    try:
        # Get the encoding
        encoding = tiktoken.get_encoding(encoding_name)

        # Encode the text and count tokens
        tokens = encoding.encode(text)
        return len(tokens)

    except Exception as e:
        logger.warning(f"failed to count tokens: {e}")
        return 0


def count_tokens_for_model(text, model_name="gpt-4"):
    """
    Count tokens for a specific model using its default encoding.

    Args:
        text (str): The text to count tokens for
        model_name (str): The model name to get encoding for

    Returns:
        int: The number of tokens in the text

    Example:
        >>> count_tokens_for_model("Hello world", "gpt-4")
        2
    """
    try:
        # Get the encoding for the specific model
        encoding = tiktoken.encoding_for_model(model_name)

        # Encode the text and count tokens
        tokens = encoding.encode(text)
        return len(tokens)

    except Exception as e:
        logger.warning(f"failed to count tokens: {e}")
        return 0


class TokenStat(threading.Thread):
    """
    Token statistics thread class for tracking token usage in LLM interactions.

    This class runs as a background thread to monitor and accumulate token counts
    and text lengths for messages sent to LLMs.

    Attributes:
        total_count (int): Total accumulated token count
        current_count (int): Token count for the current message
        total_text_len (int): Total accumulated text length
        current_text_len (int): Text length for the current message
        msg_count (int): Number of messages processed
    """

    def __init__(self, llm_id: str, lifetime: int = 86400):
        """
        Initialize the TokenStat thread.

        Args:
            llm_id (str): LLM identifier used for thread naming
            lifetime (int): Thread lifetime in seconds, <=0 means run forever,
                           defaults to 86400 seconds (24 hours)
        """
        self._start_time = int(time.time())
        self._end_time = 0
        if lifetime > 0:
            self._end_time = self._start_time + lifetime + 60
        self._last_msg_time = 0

        super(TokenStat, self).__init__(name=f"TokenStat:{llm_id}", daemon=1)
        self.total_count = 0
        self.current_count = 0

        self.total_text_len = 0
        self.current_text_len = 0

        self.msg_count = 0

        self.buffer = None
        self.rlock = threading.RLock()

        self.flag_running = True
        self.start()

    def output_token_stat(self):
        """
        Output current token statistics to the log.

        This method prints the current statistics including total and current
        token counts, text lengths, and message count.

        Returns:
            None
        """
        with self.rlock:
            info = dict(
                total_count=self.total_count,
                current_count=self.current_count,
                total_text_len=self.total_text_len,
                current_text_len=self.current_text_len,
                msg_count=self.msg_count,
            )
        msg = f"[token_stat] {info}"
        print_step(msg)
        logger.info(msg)
        return

    def add_msgs(self, msgs):
        """
        Add messages to the buffer for token calculation.

        Args:
            msgs: Messages to be sent to the LLM (list or string)

        Returns:
            None
        """
        with self.rlock:
            self.buffer = msgs

            self.msg_count = len(msgs)
            self.current_count = 0
            self.current_text_len = 0

            self._last_msg_time = int(time.time())

    def run(self):
        """
        Main thread loop for processing token statistics.

        This method runs in a separate thread and continuously monitors
        the buffer for new messages to process. It handles token counting
        and maintains thread lifecycle management.
        """
        self.flag_running = True

        # Control frequency
        count_freq = 0
        need_freq = False
        if self._end_time:
            need_freq = True

        # Maximum idle time before considering shutdown
        max_idle_time = 600

        def check():
            """
            Check if the thread should continue running.

            This internal function checks the thread's lifetime and idle time
            to determine if it should terminate.

            Returns:
                bool: True if thread should continue, False if it should stop
            """
            # Check lifetime
            if self._end_time:
                now_ts = int(time.time())
                if self._end_time < now_ts:
                    # Lifetime reached
                    if now_ts - self._last_msg_time > max_idle_time:
                        logger.info("quit due to lifetime is reached")
                        return False
                    # LLM might still be in use by some tools

            return True

        while self.flag_running:

            if need_freq:
                count_freq += 1
                # Check every 10 seconds (1000 iterations * 0.01 sleep)
                if count_freq > 1000:
                    count_freq = 0
                    if not check():
                        break

            time.sleep(0.01)
            buffer = self.buffer
            if not buffer:
                continue

            with self.rlock:
                self.buffer = None

                if not isinstance(buffer, str):
                    buffer = str(buffer)

                self.current_text_len = len(buffer)
                self.current_count = count_tokens(buffer)
                self.total_count += self.current_count
                self.total_text_len += self.current_text_len

        logger.info(f"TokenStat is exited: {self.name}")
