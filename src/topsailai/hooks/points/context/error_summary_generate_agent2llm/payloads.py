"""Narrow metadata builder for error_summary_generate_agent2llm.

Author: DawsonLin
"""

from topsailai.hooks.points.context.summary_contracts import ERROR_GENERATE_AGENT2LLM
from topsailai.hooks.points.context.summary_payloads import build_summary_payload


def build_payload(*, operation_id: str, error_category: str, failed_stage: str) -> dict:
    """Delegate exact identity and classification validation to U2."""
    return build_summary_payload(ERROR_GENERATE_AGENT2LLM, operation_id=operation_id, error_category=error_category, failed_stage=failed_stage)


__all__ = ["build_payload"]
