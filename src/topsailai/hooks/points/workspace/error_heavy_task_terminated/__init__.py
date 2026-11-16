"""Named heavy-task hard termination Hook Point.

Author: DawsonLin
"""

import logging
import sys

from topsailai.hooks.points.workspace.error_heavy_task_terminated.point import (
    NAME,
    POINT,
)
from topsailai.hooks.points.workspace.error_heavy_task_terminated.payloads import (
    build_payload,
)

logger = logging.getLogger(__name__)


def hook__workspace__error__heavy_task_terminated(**payload):
    """Validate metadata before direct dispatch; isolate ordinary observer failures."""
    try:
        from topsailai.hooks import invoke_hook_point

        metadata = build_payload(payload)
        return invoke_hook_point(NAME, **metadata)
    except Exception as error:
        try:
            # Do not log unvalidated caller data or exception text containing it.
            logger.error("Heavy-task termination observation failed point=%s category=%s",
                         NAME, type(error).__name__, exc_info=False)
        except Exception:
            try:
                # Fixed metadata only: do not expose caller data or exception text.
                sys.__stderr__.write("Heavy-task termination Hook diagnostic sink failed\n")
            except Exception:
                # Expose total diagnostic loss without replacing the business error.
                return "diagnostic_unavailable"
        return None


__all__ = ["NAME", "POINT", "hook__workspace__error__heavy_task_terminated"]
