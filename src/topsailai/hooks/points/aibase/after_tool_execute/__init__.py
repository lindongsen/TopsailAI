"""Tool execution observation entry. Author: DawsonLin."""

from topsailai.hooks.points.aibase.after_tool_execute.point import NAME


def hook__aibase__after__tool_execute(**payload):
    """Forward detached metadata to the direct-entry executor."""
    from topsailai.hooks import invoke_hook_point

    return invoke_hook_point(NAME, **payload)


__all__ = ["NAME", "hook__aibase__after__tool_execute"]
