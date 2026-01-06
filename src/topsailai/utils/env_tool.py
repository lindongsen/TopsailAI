'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-27
  Purpose: Environment variable utilities and configuration helpers
'''

import os

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
    if os.getenv("USE_TOOL_CALLS", "0") == "0":
        return False
    return True

def is_chat_multi_line() -> bool:
    """Check if multi-line chat mode is enabled.

    Multi-line chat mode is determined by the CHAT_MULTI_LINE environment variable:
    - CHAT_MULTI_LINE="0" or not set: Single-line mode (returns False)
    - CHAT_MULTI_LINE="1" or any other value: Multi-line mode (returns True)

    Returns:
        bool: True if multi-line chat mode is enabled, False otherwise
    """
    if os.getenv("CHAT_MULTI_LINE", "0") == "0":
        return False
    return True


class EnvironmentReader(object):

    @staticmethod
    def try_read_file(file_path:str) -> str:
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

    @property
    def story_prompt_content(self):
        """Retrieve story prompt content from environment variable.

        The environment variable STORY_PROMPT may contain either a file path
        or the actual content. If it's a file path, the file is read; otherwise
        the variable's value is returned directly.

        Returns:
            str: Story prompt content, or empty string if not set.
        """
        env_var = os.getenv("STORY_PROMPT")
        if not env_var:
            return ""
        content = self.try_read_file(env_var)
        return content or env_var

    def check_bool(self, name, default=None) -> bool:
        """ value in [1, true] for True """
        return str(os.getenv(name, default)).lower() in ["1", "true"]

    def get_list_str(
            self,
            name:str,
            separator:str=';',
            to_lower=False,
        ) -> list[str]|None|str:
        """
        Args:
            name (str):
            separator (str, optional): Defaults to ';'.

        Returns:
            list[str]|None|str:
              None for no config;
              str for null of config;
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
        for s in env_var.split(';'):
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

    def get(self, name, default=None):
        """Get environment variable value with default.

        Args:
            name (str): Environment variable name.
            default: Default value if variable is not set.

        Returns:
            The environment variable value or default.
        """
        return os.getenv(name, default=default)

# init
EnvReaderInstance = EnvironmentReader()
