"""Before complete-message input declaration.

Author: DawsonLin
"""

from topsailai.hooks.points.workspace.before_input_message.point import NAME, POINT

__all__ = ["NAME", "POINT"]


def hook__workspace__before__input_message():
    """Invoke this public point without a caller-owned executor or observer."""
    from topsailai.hooks import invoke_hook_point

    return invoke_hook_point(NAME)


__all__.append("hook__workspace__before__input_message")
