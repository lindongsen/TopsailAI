"""Data-only error-attempt payload validation. Author: DawsonLin."""

from topsailai.hooks.points.aibase.error_llm_chat_attempt.point import POINT
from topsailai.hooks.points.aibase.llm_chat_attempt_payloads import build_attempt_payload


def build_payload(payload, *, loop_attempts):
    """Return detached validated metadata; reject missing or unknown fields."""
    return build_attempt_payload(payload, point=POINT, loop_attempts=loop_attempts)


__all__ = ["build_payload"]
