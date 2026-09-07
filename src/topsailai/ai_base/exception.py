'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-13
Purpose:
'''


class HeavyTaskError(Exception):
    """Raised when a task is detected as too heavy and should terminate gracefully."""
    pass


class ContextWindowLimitError(Exception):
    """Raised when context cannot be reduced below the model send limit."""
    pass


class HardInterruptError(Exception):
    """Raised when a hard interrupt is requested via the control channel.

    This exception is used as a control-flow signal to stop the current
    Agent2LLM loop immediately. It must not be swallowed by generic catch-all
    handlers; the User2Agent outer loop catches it and transitions the session
    to an interrupted state until the user provides a new message.
    """
    pass


class _LLMChatRetryControlError(Exception):
    """Carry state for control decisions about one LLM chat request."""

    def __init__(
        self,
        message: str = "chat to LLM is failed",
        *,
        attempts: int,
        manual_cycle_count: int = 0,
        last_error: Exception | None = None,
        retry_reason: str = "unknown",
    ) -> None:
        """Initialize details for the LLM chat request retry decision."""
        super().__init__(message)
        self.attempts = attempts
        self.manual_cycle_count = manual_cycle_count
        self.last_error = last_error
        self.retry_reason = retry_reason


class LLMRetryExhaustedError(_LLMChatRetryControlError):
    """Report terminal exhaustion of bounded retries for one LLM chat request."""


class LLMBackToChatError(_LLMChatRetryControlError):
    """Request that User2Agent abandon this turn and read a new user message."""
