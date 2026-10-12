"""Narrow metadata builder for before_summary_generate_user2agent.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import BEFORE_GENERATE_USER2AGENT
from topsailai.hooks.points.context.summary_payloads import build_summary_payload


def build_payload(*, operation_id: str) -> dict:
    """Delegate exact identity and classification validation to U2."""
    return build_summary_payload(BEFORE_GENERATE_USER2AGENT, operation_id=operation_id)


__all__ = ["build_payload"]
