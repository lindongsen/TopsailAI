"""Named heavy-task advisory warning Hook Point.

Author: DawsonLin
"""

import logging
import sys

from topsailai.hooks.points.workspace.after_heavy_task_warning.point import (
    NAME,
    POINT,
)
from topsailai.hooks.points.workspace.after_heavy_task_warning.payloads import (
    build_payload,
)

logger = logging.getLogger(__name__)


def hook__workspace__after__heavy_task_warning(**payload):
    """Validate metadata before direct dispatch; isolate ordinary observer failures."""
    try:
        from topsailai.hooks import invoke_hook_point

        metadata = build_payload(payload)
        return invoke_hook_point(NAME, **metadata)
    except Exception as error:
        try:
            # Do not log unvalidated caller data or exception text containing it.
            logger.error("Heavy-task warning observation failed point=%s category=%s",
                         NAME, type(error).__name__, exc_info=False)
        except Exception:
            try:
                # Fixed metadata only: do not expose caller data or exception text.
                sys.__stderr__.write("Heavy-task warning Hook diagnostic sink failed\n")
            except Exception:
                # Expose total diagnostic loss without raising into the agent turn.
                return "diagnostic_unavailable"
        return None


__all__ = ["NAME", "POINT", "hook__workspace__after__heavy_task_warning"]
