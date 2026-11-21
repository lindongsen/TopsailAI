"""Shared helpers for tests that must observe ``time.sleep`` calls.

Patching ``time.sleep`` on a module that does ``import time`` replaces the
attribute on the shared global ``time`` module, so the patch reaches every
thread and every caller in the process. Any assertion built on such a mock then
measures the whole process instead of the code under test, and unrelated
background threads turn the assertion into a load-dependent coin flip.

``module_time`` replaces the module's own ``time`` reference with a stand-in
that records ``sleep`` calls and delegates every other attribute to the real
module, so the measurement stays scoped to the module under test.
"""

import time as real_time
from contextlib import contextmanager
from unittest.mock import patch


class RecordingTime:
    """Stand-in for the ``time`` module that records ``sleep`` calls.

    Attributes other than ``sleep`` are delegated to the real ``time`` module,
    so elapsed-time arithmetic such as ``monotonic`` keeps working.
    """

    def __init__(self):
        """Create an empty sleep-call recorder."""
        self.sleeps = []

    def sleep(self, seconds):
        """Record the requested duration instead of blocking."""
        self.sleeps.append(seconds)

    def __getattr__(self, name):
        """Delegate any other attribute to the real ``time`` module."""
        return getattr(real_time, name)


@contextmanager
def module_time(module):
    """Patch ``module.time`` with a recorder scoped to that module only.

    Args:
        module: The module object whose ``time`` reference should be replaced.

    Yields:
        RecordingTime: Recorder exposing ``sleeps``, the list of requested
        sleep durations in call order.
    """
    recorder = RecordingTime()
    with patch.object(module, "time", recorder):
        yield recorder


def module_time_patch(module):
    """Decorator form of :func:`module_time` for ``@patch``-style tests.

    Injects the recorded sleep durations as a plain list under the ``mock_sleep``
    keyword, matching the long-standing convention in
    ``test_topsailai_ai_base_llm_base.py`` where tests assert
    ``self.assertEqual(mock_sleep, [5, 10, 5])``. A list is injected rather than
    the recorder object so both call styles stay interchangeable.

    Args:
        module: The module object whose ``time`` reference should be replaced.

    Returns:
        Callable: Decorator that runs the test inside :func:`module_time`.
    """
    import functools

    def decorator(func):
        """Wrap ``func`` so it runs with a module-scoped time recorder."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """Run the test with the recorded durations injected as a list."""
            with module_time(module) as recorder:
                kwargs["mock_sleep"] = recorder.sleeps
                return func(*args, **kwargs)

        return wrapper

    return decorator
