"""Explicit point boundary for error_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.error_summary_generate_agent2llm.point import NAME, POINT
from topsailai.hooks.points.context.error_summary_generate_agent2llm.payloads import build_payload

__all__ = ["NAME", "POINT", "build_payload"]


def hook__context__error__summary_generate_agent2llm(*, operation_id: str, error_category: str, failed_stage: str):
    """Invoke this summary checkpoint without a caller-owned executor."""
    from topsailai.hooks.points.context.summary_payloads import invoke_summary_hook_point

    payload = build_payload(operation_id=operation_id, error_category=error_category, failed_stage=failed_stage)
    return invoke_summary_hook_point(NAME, payload)


__all__.append("hook__context__error__summary_generate_agent2llm")
