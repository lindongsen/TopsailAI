"""Explicit point boundary for before_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.before_summary_generate_agent2llm.point import NAME, POINT
from topsailai.hooks.points.context.before_summary_generate_agent2llm.payloads import build_payload

__all__ = ["NAME", "POINT", "build_payload"]


def hook__context__before__summary_generate_agent2llm(*, operation_id: str):
    """Invoke this summary checkpoint without a caller-owned executor."""
    from topsailai.hooks.points.context.summary_payloads import invoke_summary_hook_point

    payload = build_payload(operation_id=operation_id)
    return invoke_summary_hook_point(NAME, payload)


__all__.append("hook__context__before__summary_generate_agent2llm")
