"""Named LLM request failure report Hook Point. Author: DawsonLin."""

import logging
import sys

from topsailai.hooks.points.aibase.after_llm_request_failures.point import NAME, POINT
from topsailai.hooks.points.aibase.after_llm_request_failures.payloads import (
    build_payload,
)

logger = logging.getLogger(__name__)


def hook__aibase__after__llm_request_failures(**payload):
    """Validate metadata before direct dispatch; isolate ordinary observer failures."""
    try:
        from topsailai.hooks import invoke_hook_point

        metadata = build_payload(payload)
        return invoke_hook_point(NAME, **metadata)
    except Exception as error:
        try:
            # Do not log unvalidated caller data or exception text containing it.
            logger.error("LLM request failure report failed point=%s category=%s",
                         NAME, type(error).__name__, exc_info=False)
        except Exception:
            try:
                # Fixed metadata only: do not expose caller data or exception text.
                sys.__stderr__.write("LLM request failure Hook diagnostic sink failed\n")
            except Exception:
                # Expose total diagnostic loss without raising into the request.
                return "diagnostic_unavailable"
        return None


__all__ = ["NAME", "POINT", "hook__aibase__after__llm_request_failures"]
