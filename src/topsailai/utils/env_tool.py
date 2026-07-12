"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-27
Purpose: Environment variable utilities and configuration helpers
"""

import os
from contextlib import contextmanager

from topsailai.logger import logger


# Values considered truthy when parsing boolean environment variables.
# Covers common affirmative spellings used across the project.
_TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}


def is_true(value: str | None) -> bool:
    """Return True when value represents an affirmative boolean setting.

    Truthy values (case-insensitive): "1", "true", "yes", "on", "enabled".
    Anything else (including None and empty string) is treated as False.

    Args:
        value: Raw environment variable value, or None when unset.

    Returns:
        bool: True for affirmative values, False otherwise.
    """
    if value is None:
        return False
    return str(value).strip().lower() in _TRUTHY_VALUES


@contextmanager
def ctxm_set_env(kv: dict):
    """Temporarily set environment variables.

    Args:
        kv: Mapping of environment variable names to values. A value of None
            removes the variable if it exists.

    Yields:
        dict: Original values for variables that existed before the override.
    """
    old_kv = {}
    for k in kv.keys():
        old_v = os.getenv(k)
        if old_v is not None:
            old_kv[k] = old_v

    try:
        for k, v in kv.items():
            if v is None:
                if k in os.environ:
                    del os.environ[k]
            else:
                os.environ[k] = v
        yield old_kv
    finally:
        for k, v in old_kv.items():
            os.environ[k] = v
        for k, v in kv.items():
            if k not in old_kv:
                if k in os.environ:
                    del os.environ[k]


@contextmanager
def ctxm_hide_env(keys):
    """Temporarily hide environment variables.

    Args:
        keys: A single environment variable name or a list of names to hide.

    Yields:
        dict: Original values for the hidden variables.
    """
    if isinstance(keys, str):
        keys = [keys]

    ori_data = {}
    try:
        for k in keys:
            v = os.getenv(k)
            if v is None:
                continue
            ori_data[k] = v
            del os.environ[k]
        yield ori_data
    finally:
        for k, v in ori_data.items():
            os.environ[k] = v


def get_session_id() -> str | None:
    """Get session identifier from environment variables."""
    return (
        os.getenv("TOPSAILAI_SESSION_ID")
        or os.getenv("SESSION_ID")
    )


def is_interactive_mode() -> bool:
    """Check if running in interactive mode, default is True."""
    if os.getenv("TOPSAILAI_INTERACTIVE_MODE", "1") == "0":
        return False
    return True


def is_debug_mode():
    """Check if the application is running in debug mode.

    Debug mode is determined by the DEBUG environment variable:
    - DEBUG="0" or not set: Production mode (returns False)
    - DEBUG="1" or any other value: Debug mode (returns True)

    Returns:
        bool: True if debug mode is enabled, False otherwise
    """
    if os.getenv("DEBUG", "0") == "0":
        return False
    return True


def is_use_tool_calls() -> bool:
    """Check if tool calls functionality is enabled.

    Tool calls functionality is determined by the USE_TOOL_CALLS environment variable:
    - USE_TOOL_CALLS="0" or not set: Tool calls disabled (returns False)
    - USE_TOOL_CALLS="1" or any other value: Tool calls enabled (returns True)

    Returns:
        bool: True if tool calls are enabled, False otherwise
    """
    if os.getenv("USE_TOOL_CALLS", "0") != "0" or \
            os.getenv("TOPSAILAI_USE_TOOL_CALLS", "0") != "0":
        return True
    return False


def get_history_load_max_entries(default: int = 100) -> int:
    """Return the maximum number of history entries to load into memory.

    Reads ``TOPSAILAI_HISTORY_LOAD_MAX_ENTRIES``. Values that are unset,
    empty, or cannot be parsed as a positive integer fall back to *default*.
    Negative or zero values are clamped to *default* so that history loading
    always has a sensible limit.

    Args:
        default: Number of entries to use when the variable is not set or
            invalid. Defaults to 100.

    Returns:
        int: Maximum number of history entries to load.
    """
    value = os.getenv("TOPSAILAI_HISTORY_LOAD_MAX_ENTRIES")
    if not value:
        return default
    try:
        max_entries = int(value)
    except (TypeError, ValueError):
        return default
    if max_entries <= 0:
        return default
    return max_entries


def is_chat_multi_line() -> bool:
    """Check if multi-line chat mode is enabled.

    Multi-line chat mode is determined by the CHAT_MULTI_LINE environment variable:
    - CHAT_MULTI_LINE="0" or not set: Single-line mode (returns False)
    - CHAT_MULTI_LINE="1" or any other value: Multi-line mode (returns True)

    Returns:
        bool: True if multi-line chat mode is enabled, False otherwise
    """
    if os.getenv("TOPSAILAI_CHAT_MULTI_LINE", "0") != "0":
        return True

    if os.getenv("CHAT_MULTI_LINE", "0") != "0":
        return True

    return False


def is_input_pipe_enabled() -> bool:
    """Check if pipe-based input is enabled.

    Pipe input is controlled by the ``TOPSAILAI_INPUT_PIPE_ENABLED``
    environment variable. When enabled, interactive ``input()`` calls are
    redirected to read from a session-scoped named pipe instead of stdin.

    Returns:
        bool: True when ``TOPSAILAI_INPUT_PIPE_ENABLED`` is set to a truthy
        value (e.g. ``"1"`` or ``"true"``), False otherwise.
    """
    return is_true(os.getenv("TOPSAILAI_INPUT_PIPE_ENABLED"))


def get_input_pipe_timeout() -> float | None:
    """Return the timeout in seconds for pipe-based input.

    Reads ``TOPSAILAI_INPUT_PIPE_TIMEOUT``. An empty, unset, or invalid value
    means no timeout (wait indefinitely). A positive float is returned as the
    timeout duration.

    Returns:
        float | None: Timeout in seconds, or ``None`` for no timeout.
    """
    value = os.getenv("TOPSAILAI_INPUT_PIPE_TIMEOUT")
    if not value:
        return None
    try:
        timeout = float(value)
        return timeout if timeout > 0 else None
    except (TypeError, ValueError):
        return None


def is_need_print() -> bool:
    if is_debug_mode():
        return True
    if is_interactive_mode():
        return True
    return False


class EnvironmentReader(object):
    """Base class to read environment variables."""

    @property
    def project_folder(self) -> str | None:
        """Current project folder.

        Returns:
            str|None: Resolved project folder path.
        """
        return (
            EnvReaderInstance.get("TOPSAILAI_PROJECT_WORKSPACE")
            or EnvReaderInstance.get("TOPSAILAI_PROJECT_PWD")
            or EnvReaderInstance.get("TOPSAILAI_PWD")
        )

    @staticmethod
    def try_read_file(file_path: str) -> str:
        """Attempt to read content from a file path.

        This method checks if the given path is a valid file and reads its content.
        It handles cases where the path might not be a file (e.g., environment variable
        containing direct content). Only reads files if path starts with '.' or '/' or
        length <= 255 and the file exists.

        Args:
            file_path (str): Path to a file, or possibly not a file.

        Returns:
            str: File content stripped of whitespace, or empty string if not a file.
        """
        if not file_path:
            return ""
        if file_path[0] in "./" or len(file_path) <= 255:
            if os.path.exists(file_path):
                with open(file_path, encoding="utf-8") as fd:
                    return fd.read().strip()
        return ""

    @staticmethod
    def read_file_or_content(env_key: str) -> str:
        """Environment variable may be a file; if so, return file content.

        Args:
            env_key (str): Environment variable name.

        Returns:
            str: File content or the raw variable value.
        """
        env_var = os.getenv(env_key)
        if not env_var:
            return ""
        content = EnvironmentReader.try_read_file(env_var)
        return content or env_var

    @property
    def story_prompt_content(self):
        """Retrieve story prompt content from environment variable.

        The environment variable TOPSAILAI_STORY_PROMPT may contain either a file path
        or the actual content. If it's a file path, the file is read; otherwise
        the variable's value is returned directly.

        Returns:
            str: Story prompt content, or empty string if not set.
        """
        env_var = os.getenv("TOPSAILAI_STORY_PROMPT")
        if not env_var:
            return ""
        content = self.try_read_file(env_var)
        return content or env_var

    @property
    def context_user_message_content(self):
        """Retrieve context user message content from environment variable.

        The environment variable TOPSAILAI_CONTEXT_USER_MESSAGE may contain either
        a file path or the actual content. If it's a file path, the file is read;
        otherwise the variable's value is returned directly.

        Returns:
            str: Context user message content, or empty string if not set.
        """
        env_var = os.getenv("TOPSAILAI_CONTEXT_USER_MESSAGE")
        if not env_var:
            return ""
        content = self.try_read_file(env_var)
        return content or env_var

    def clean_context_x_message(self):
        """Only use once in a session."""
        for env_key in [
            "TOPSAILAI_CONTEXT_USER_MESSAGE",
        ]:
            if env_key in os.environ:
                os.environ[env_key] = ""
        return

    def check_bool(self, name, default=None) -> bool:
        """Return True when the environment variable represents an affirmative value.

        Truthy values (case-insensitive): "1", "true", "yes", "on", "enabled".
        When the variable is unset, *default* is normalized the same way if it is
        a string; otherwise it is converted via ``bool()``.
        """
        value = os.getenv(name)
        if value is None:
            if default is None:
                return False
            if isinstance(default, str):
                return is_true(default.lower())
            return bool(default)
        return is_true(str(value).lower())

    def get_list_str(
            self,
            name: str,
            separator: str = ';',
            to_lower=False,
    ) -> list[str] | None | str:
        """Parse an environment variable as a list of strings.

        Args:
            name (str): Environment variable name.
            separator (str, optional): Defaults to ';'.
            to_lower (bool, optional): Convert items to lowercase.

        Returns:
            list[str]|None|str:
              None when the variable is not set;
              str (empty) when the variable is set but empty;
              list[str] otherwise.
        """
        env_var = os.getenv(name)
        if env_var is None:
            # no config
            return None
        env_var = env_var.strip()
        if not env_var:
            # null of config
            return env_var
        result = set()
        env_var_list = []
        if separator:
            env_var_list = env_var.split(separator)
        else:
            env_var_list = env_var.replace(',', ';').split(';')
        for s in env_var_list:
            s = s.strip()
            if not s:
                continue
            if to_lower:
                s = s.lower()
            result.add(s)
        return list(result)

    def is_not_config(self, name):
        return name not in os.environ

    def is_null_config(self, name):
        return self.get(name) == ""

    def get(self, name, default=None, formatter=None):
        """Get environment variable value with default.

        Args:
            name (str): Environment variable name.
            default: Default value if variable is not set.
            formatter: format value, new_v = func(v)

        Returns:
            The environment variable value or default.
        """
        v = os.getenv(name, default=default)
        if v is not None and formatter and callable(formatter):
            try:
                if formatter in (int, float) and v == "":
                    v = None
                else:
                    v = formatter(v)
            except Exception as e:
                logger.exception("key=%s, value=%s, exception=%s", name, v, e)
                v = None
        if v is None:
            v = default
        return v


# init
EnvReaderInstance = EnvironmentReader()
