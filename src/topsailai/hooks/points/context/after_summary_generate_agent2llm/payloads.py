"""Narrow metadata builder for after_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import AFTER_GENERATE_AGENT2LLM
from topsailai.hooks.points.context.summary_payloads import build_summary_payload


def build_payload(*, operation_id: str) -> dict:
    """Delegate exact identity and classification validation to U2."""
    return build_summary_payload(AFTER_GENERATE_AGENT2LLM, operation_id=operation_id)


__all__ = ["build_payload"]
