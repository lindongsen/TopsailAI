'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose:
'''

import shlex

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
    format_tool,
    cmd_tool,
)

DEFAULT_CMD_TIMEOUT = 300


def get_hook_scripts_info(key:str) -> dict:
    """
    Retrieve hook script information from environment variable.

    Reads hook scripts from the specified environment variable key. Each script
    entry should be in the format: "{script_file} {cmd_options}", where multiple
    scripts are separated by semicolons.

    Args:
        key: The environment variable key to read hook scripts from.

    Returns:
        A dictionary mapping script file paths to their command options.
        Each script file maps to a dict of key-value pairs from cmd_options.
        Returns empty dict if no scripts are configured.

    Example:
        # If env var HOOK_KEY="script1.py timeout=30; script2.py timeout=60 env_keys=KEY1,KEY2"
        # Returns: {"script1.py": {"timeout": "30"}, "script2.py": {"timeout": "60", "env_keys": ["KEY1", "KEY2"]}}
    """
    result = {}

    # Format: "{script_file} {cmd_options}"
    # e.g. "script_file1 k1=v1 k2=v2; script_file2 k1=v1 k2=v2"
    env_scripts = env_tool.EnvReaderInstance.get_list_str(key, separator=';')
    if not env_scripts:
        return result

    for script_info in env_scripts:
        script_info_list = shlex.split(script_info)
        script_file = script_info_list[0]
        cmd_options = {}
        for kv_str in script_info_list[1:]:
            k, v = kv_str.split('=', 1)
            if ',' in v:
                # list
                v = v.split(',')
            cmd_options[k] = v
        result[script_file] = cmd_options
    return result

def build_cmd_parameters(script_file:str, cmd_options:dict) -> dict:
    """
    Build command parameters for executing a hook script.

    Constructs a dictionary of parameters needed to execute a hook script via
    cmd_tool.exec_cmd(). Includes the script command, timeout setting, and
    environment variables to pass.

    Args:
        script_file: Path to the script file to execute.
        cmd_options: Dictionary of command options parsed from the hook config.
            May contain:
            - timeout: Custom timeout in seconds (defaults to DEFAULT_CMD_TIMEOUT)
            - env_keys: Additional environment variable keys to pass (comma-separated)

    Returns:
        A dictionary containing:
        - cmd: The script file path
        - timeout: Execution timeout in seconds
        - env_keys: List of environment variable names to include

    Example:
        >>> build_cmd_parameters("script.py", {"timeout": "60", "env_keys": "KEY1,KEY2"})
        {"cmd": "script.py", "timeout": 60, "env_keys": ["SESSION_ID", "TOPSAILAI_TASK_ID", "KEY1", "KEY2"]}
    """
    result = dict(
        cmd=script_file,
        timeout=cmd_options.get("timeout") or DEFAULT_CMD_TIMEOUT,
        env_keys=[
            "SESSION_ID",
            "TOPSAILAI_SESSION_ID",
            "TOPSAILAI_TASK_ID",
        ],
    )

    env_keys = cmd_options.get("env_keys")
    if env_keys:
        result["env_keys"] += format_tool.to_list(env_keys)

    return result

def call_hook_scripts(key:str, env_info:dict) -> dict:
    """
    Execute all hook scripts associated with the given environment variable key.

    Reads hook script configurations from the specified environment variable,
    builds command parameters for each script, and executes them sequentially.
    Each script is executed with the configured timeout and environment variables.

    Args:
        key: The environment variable key that contains hook script configurations.
            The value should be in the format: "script_file1 opt1=val1; script_file2 opt2=val2"

    Returns:
        A dictionary mapping each script file path to its execution result.
        If a script fails to execute, the result will be None and the exception
        will be logged but not raised.

    Example:
        # If env var PRE_HOOK="script1.py timeout=30; script2.py timeout=60"
        >>> call_hook_scripts("PRE_HOOK")
        {"script1.py": "success output", "script2.py": "success output"}
    """
    result = {}
    script_info = get_hook_scripts_info(key)
    if not script_info:
        return result

    for script_file, cmd_options in script_info.items():
        ret = None
        try:
            cmd_parameters = build_cmd_parameters(script_file, cmd_options)

            if env_info:
                if "env_info" not in cmd_parameters:
                    cmd_parameters["env_info"] = {}
                cmd_parameters["env_info"].update(env_info)

            ret = cmd_tool.exec_cmd(**cmd_parameters)
            logger.info("call hook done: [%s], [%s], %s", key, script_file, ret)
        except Exception as e:
            logger.exception("call hook failed: [%s], %s", key, e)
        finally:
            result[script_file] = ret

    return result
