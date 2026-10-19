"""PromptBase initialization completion Hook Point.

Author: DawsonLin
"""

from topsailai.hooks.points.aibase.after_prompt_base_init.point import NAME, POINT

__all__ = ["NAME", "POINT"]


def hook__aibase__after__prompt_base_init(*, prompt_base):
    """Forward the live PromptBase instance to in-process Modules."""
    from topsailai.hooks import invoke_hook_point

    return invoke_hook_point(NAME, prompt_base=prompt_base)


__all__.append("hook__aibase__after__prompt_base_init")
