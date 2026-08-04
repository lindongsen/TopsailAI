'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-13
Purpose:
'''


class HeavyTaskError(Exception):
    """Raised when a task is detected as too heavy and should terminate gracefully."""
    pass


class HardInterruptError(Exception):
    """Raised when a hard interrupt is requested via the control channel.

    This exception is used as a control-flow signal to stop the current
    Agent2LLM loop immediately. It must not be swallowed by generic catch-all
    handlers; the User2Agent outer loop catches it and transitions the session
    to an interrupted state until the user provides a new message.
    """
    pass
