'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-16
Purpose: Bottom-line guard that terminates a turn when recent LLM traffic is
         dominated by summary requests.
'''

from collections import deque

from topsailai.utils.env_tool import EnvReaderInstance


# Default number of most recent LLM requests kept in the sliding window.
SUMMARY_WINDOW_SIZE_DEFAULT = 10

# Default number of summary requests tolerated inside that window. The guard
# fires only when the count is strictly greater than this value.
SUMMARY_WINDOW_MAX_SUMMARIES_DEFAULT = 3

# Attribute name used to store the per-agent guard on the agent object. The
# guard lives on the agent rather than on one LLMModel instance because the
# default summary processor builds an independent model, so a per-model window
# would never observe the summary requests it is meant to count.
GUARD_ATTRIBUTE_NAME = "_summary_window_guard"


def _read_positive_int(env_reader, name, default):
    """Read a positive integer setting, falling back to the default.

    Args:
        env_reader: Reader exposing ``get``.
        name (str): Environment variable name.
        default (int): Value used when the setting is missing or invalid.

    Returns:
        int: A positive integer, or ``default``.
    """
    raw = env_reader.get(name, default=default)
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return value


def _read_non_negative_int(env_reader, name, default):
    """Read a non-negative integer setting, falling back to the default.

    Args:
        env_reader: Reader exposing ``get``.
        name (str): Environment variable name.
        default (int): Value used when the setting is missing or invalid.

    Returns:
        int: A non-negative integer, or ``default``.
    """
    raw = env_reader.get(name, default=default)
    if isinstance(raw, bool):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return default
    return value


def get_summary_window_size(env_reader=None):
    """Return how many recent LLM requests the window keeps.

    The value is read at call time so an operator can tune it on a running
    process.

    Args:
        env_reader: Optional reader exposing ``get``. Defaults to
            ``EnvReaderInstance``.

    Returns:
        int: Positive window size.
    """
    if env_reader is None:
        env_reader = EnvReaderInstance
    return _read_positive_int(
        env_reader,
        "TOPSAILAI_SUMMARY_WINDOW_SIZE",
        SUMMARY_WINDOW_SIZE_DEFAULT,
    )


def get_summary_window_max_summaries(env_reader=None):
    """Return how many summary requests are tolerated inside the window.

    The guard fires only when the observed count is strictly greater than this
    value. ``0`` disables the guard, matching the project convention that a
    zero threshold turns a check off.

    Args:
        env_reader: Optional reader exposing ``get``. Defaults to
            ``EnvReaderInstance``.

    Returns:
        int: Non-negative tolerated summary count.
    """
    if env_reader is None:
        env_reader = EnvReaderInstance
    return _read_non_negative_int(
        env_reader,
        "TOPSAILAI_SUMMARY_WINDOW_MAX_SUMMARIES",
        SUMMARY_WINDOW_MAX_SUMMARIES_DEFAULT,
    )


class SummaryWindowGuard(object):
    """Count summary requests inside a sliding window of recent LLM requests.

    The window holds the return mode of the most recent LLM requests, so the
    denominator grows with ordinary traffic exactly as it does in production.
    A summary request is any request whose return mode is ``raw``.

    The guard is deliberately a bottom-line net: it does not try to judge
    whether a summary was useful, it only stops a turn whose recent traffic is
    dominated by summarization.
    """

    def __init__(self, window_size=None, max_summaries=None, env_reader=None):
        """Initialize the guard.

        Args:
            window_size (int, optional): Window size. Read at call time when
                omitted.
            max_summaries (int, optional): Tolerated summary count. Read at
                call time when omitted.
            env_reader (optional): Reader exposing ``get``. Defaults to
                ``EnvReaderInstance`` when omitted.
        """
        self._window_size = window_size
        self._max_summaries = max_summaries
        self._env_reader = env_reader
        self._modes = deque()

    def _resolve_window_size(self):
        """Return the effective window size, reading configuration if needed."""
        if self._window_size is not None:
            return self._window_size
        return get_summary_window_size(self._env_reader)

    def _resolve_max_summaries(self):
        """Return the effective tolerated count, reading configuration if needed."""
        if self._max_summaries is not None:
            return self._max_summaries
        return get_summary_window_max_summaries(self._env_reader)

    def record(self, return_mode):
        """Record one LLM request and report whether the limit is exceeded.

        The current request is included in the count, so the guard stops before
        the offending request is sent.

        Args:
            return_mode (str): Return mode of the request; ``raw`` marks a
                summary request.

        Returns:
            tuple: ``(exceeded, summary_count, window_size, max_summaries)``.
        """
        window_size = self._resolve_window_size()
        max_summaries = self._resolve_max_summaries()

        self._modes.append(return_mode)
        while len(self._modes) > window_size:
            self._modes.popleft()

        summary_count = sum(1 for mode in self._modes if mode == "raw")
        exceeded = max_summaries > 0 and summary_count > max_summaries
        return exceeded, summary_count, window_size, max_summaries

    def reset(self):
        """Drop every recorded request."""
        self._modes.clear()

    def snapshot(self):
        """Return the recorded return modes, oldest first."""
        return list(self._modes)


def get_agent_summary_window_guard(agent):
    """Return the guard owned by one agent, creating it on first use.

    Args:
        agent: Agent object that owns the guard.

    Returns:
        SummaryWindowGuard | None: The guard, or ``None`` when no agent was
        supplied.
    """
    if agent is None:
        return None
    guard = getattr(agent, GUARD_ATTRIBUTE_NAME, None)
    # A test double such as MagicMock auto-creates any attribute, so an
    # attribute that merely exists is not proof of a real guard. Trusting it
    # would call a mock ``record()`` whose return value cannot be unpacked and
    # would break every caller that supplies a mock agent.
    if not isinstance(guard, SummaryWindowGuard):
        guard = SummaryWindowGuard()
        setattr(agent, GUARD_ATTRIBUTE_NAME, guard)
    return guard
