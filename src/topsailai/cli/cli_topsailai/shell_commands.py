"""Interactive shell-command execution for the TopsailAI CLI."""

from __future__ import annotations

import shlex

from cli_topsailai.colors import print_error
from cli_topsailai.process import run_external_command


def execute_shell_command(user_input: str) -> int:
    """Execute the command after ``!`` using the same os.system path as /git.

    The command line is parsed with shell-like rules and executed through the
    shared ``run_external_command`` helper with ``use_os_system=True``, the
    exact execution path used by the YAML ``/git`` commands. This prints an
    ``Executing (os.system): <cmd> ...`` info line, streams the command's own
    output, reports a non-zero exit status as ``Command exited with code N.``,
    and finishes with ``Execution completed.``. The command runs in the CLI
    process working directory and inherits its environment.

    Returns:
        0 when the command was launched and completed; 1 when the command is
        empty, unparsable, or fails to launch. The shell command's own exit
        status is reported (not returned) by the shared execution helper.
    """
    command = user_input[1:].strip()
    if not command:
        print_error("Usage: !<command>")
        return 1
    try:
        cmd_list = shlex.split(command)
    except ValueError as error:
        print_error(f"Failed to parse command: {error}")
        return 1
    if not cmd_list:
        print_error("Usage: !<command>")
        return 1
    try:
        run_external_command(
            cmd_list,
            {},
            independent=False,
            async_cmd=False,
            use_os_system=True,
        )
    # Keep the YAML /git handler's broad execution-boundary guard.
    except Exception as error:
        print_error(f"Failed to execute command: {error}")
        return 1
    return 0
