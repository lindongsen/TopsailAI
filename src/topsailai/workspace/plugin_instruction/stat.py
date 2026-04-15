'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Provides instruction handlers for displaying tool call statistics
           and errors in the workspace plugin system.

  This module integrates with the tool_stat module to provide commands for:
  - Viewing tool call statistics (tool_call)
  - Viewing tool call errors (tool_call_errors)
  - Resetting statistics (tool_call_reset)
'''

from topsailai.logger import logger
from topsailai.utils import (
    json_tool,
)
from topsailai.context import tool_stat


def show_tool_call_stat(tool_name: str = None) -> None:
    """
    Display tool call statistics from the default ToolStat instance.

    This function retrieves and prints statistics about tool calls that have been
    recorded. It can show statistics for all tools or filter by a specific tool name.

    Args:
        tool_name (str, optional):
            The name of a specific tool to display statistics for.
            If None, statistics for all tools will be displayed.
            Defaults to None.
    """
    # Get the default statistics instance
    stat = tool_stat.get_default_stat()

    # Retrieve all statistics data
    stat_info = stat.stat

    # Return silently if no statistics have been recorded
    if not stat_info:
        return

    # Filter by tool_name if specified
    if tool_name:
        # Check if the specified tool exists in statistics
        if tool_name not in stat_info:
            return

        # Print statistics for the specific tool
        print(
            json_tool.safe_json_dump(
                stat_info.get(tool_name),
                indent=2,
            )
        )
        return

    # Print statistics for all tools
    print(json_tool.safe_json_dump(stat_info, indent=2))


def show_tool_call_errors(tool_name: str = None) -> None:
    """
    Display tool call errors from the default ToolStat instance.

    This function retrieves and prints information about failed tool calls (errors).
    It can show errors for all tools or filter by a specific tool name.

    Args:
        tool_name (str, optional):
            The name of a specific tool to display errors for.
            If None, errors for all tools will be displayed.
            Defaults to None.
    """
    # Get the default statistics instance
    stat = tool_stat.get_default_stat()

    # Retrieve error information
    error_info = stat.errors

    # Return silently if no errors have been recorded
    if not error_info:
        return

    # Filter by tool_name if specified
    if tool_name:
        # Check if the specified tool exists in error records
        if tool_name not in error_info:
            return

        # Print errors for the specific tool
        print(
            json_tool.safe_json_dump(
                error_info.get(tool_name),
                indent=2
            )
        )
        return

    # Print errors for all tools
    print(json_tool.safe_json_dump(error_info, indent=2))


def log_tool_call():
    """ Export tool_call info to log file """
    stat = tool_stat.get_default_stat()
    content = stat.export_json()
    logger.info("ToolStat of tool_calls:\n [%s]", content)
    print("DONE")
    return

# Instruction mapping for the workspace plugin system
# Maps instruction command names to their corresponding handler functions
#
# Available instructions:
#   - tool_call: Display tool call statistics (see show_tool_call_stat)
#   - tool_call_errors: Display tool call errors (see show_tool_call_errors)
#   - tool_call_reset: Reset all statistics to initial state
#
# Usage in plugin system:
#   The workspace plugin can invoke these instructions by name:
#   >>> instruction = INSTRUCTIONS["tool_call"]
#   >>> instruction()           # Show all statistics
#   >>> instruction("api_call") # Show statistics for specific tool
INSTRUCTIONS = dict(
    tool_call=show_tool_call_stat,                    # Display tool call statistics
    tool_call_errors=show_tool_call_errors,          # Display tool call errors
    tool_call_reset=tool_stat.get_default_stat().reset,  # Reset all statistics
    tool_call_log=log_tool_call,
)
