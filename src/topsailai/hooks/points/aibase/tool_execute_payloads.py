"""Detached tool-execution observation metadata. Author: DawsonLin."""

import logging

logger = logging.getLogger(__name__)


def build_tool_execute_payload(tool_func, args, tool_name):
    """Build detached metadata without invoking any Hook Point."""
    try:
        name = tool_name if tool_name is not None else getattr(tool_func, "__name__", None)
        name = name if type(name) is str else None
        keys = tuple(sorted(key for key in args if type(key) is str)) if type(args) is dict else ()
        return dict(tool_name=name, argument_count=len(args) if type(args) is dict else None,
                    argument_keys=keys)
    except Exception:
        logger.exception("Tool execution metadata preparation failed")
        return dict(tool_name=None, argument_count=None, argument_keys=())
