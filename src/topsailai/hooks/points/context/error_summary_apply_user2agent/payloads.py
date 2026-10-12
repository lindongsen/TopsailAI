"""Narrow metadata builder for error_summary_apply_user2agent.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import ERROR_APPLY_USER2AGENT
from topsailai.hooks.points.context.summary_payloads import build_summary_payload


def build_payload(*, operation_id: str, error_category: str, failed_stage: str, partial_apply_possible: bool) -> dict:
    """Delegate exact identity and classification validation to U2."""
    return build_summary_payload(ERROR_APPLY_USER2AGENT, operation_id=operation_id, error_category=error_category, failed_stage=failed_stage, partial_apply_possible=partial_apply_possible)


__all__ = ["build_payload"]
