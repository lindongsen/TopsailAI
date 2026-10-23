"""Named LLM chat attempt after Hook Point. Author: DawsonLin."""

import logging
import sys

from topsailai.hooks.points.aibase.after_llm_chat_attempt.point import NAME, POINT
from topsailai.hooks.points.aibase.after_llm_chat_attempt.payloads import build_payload

logger = logging.getLogger(__name__)


def hook__aibase__after__llm_chat_attempt(*, loop_attempts=None, **payload):
    """Validate metadata before direct dispatch; isolate ordinary observer failures."""
    try:
        from topsailai.hooks import invoke_hook_point

        metadata = build_payload(payload, loop_attempts=loop_attempts)
        return invoke_hook_point(NAME, **metadata)
    except Exception as error:
        try:
            # Do not log unvalidated caller data or exception text containing it.
            logger.error("LLM attempt observation failed point=%s category=%s",
                         NAME, type(error).__name__, exc_info=False)
        except Exception:
            try:
                # Fixed metadata only: do not expose caller data or exception text.
                sys.__stderr__.write("LLM attempt Hook diagnostic sink failed\n")
            except Exception:
                # Expose total diagnostic loss without raising into business retries.
                return "diagnostic_unavailable"
        return None


__all__ = ["NAME", "POINT", "hook__aibase__after__llm_chat_attempt"]
