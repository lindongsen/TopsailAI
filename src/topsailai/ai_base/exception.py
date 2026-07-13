'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-13
Purpose:
'''


class HeavyTaskError(Exception):
    """Raised when a task is detected as too heavy and should terminate gracefully."""
    pass
