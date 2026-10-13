"""Best-effort metadata-only summary observation. Author: DawsonLin."""

import logging

from topsailai.events import record_event
from topsailai.hooks.contracts import _thaw_frozen_json
from topsailai.hooks.points.context.summary_payloads import build_summary_hook_context

logger = logging.getLogger(__name__)


def main(*, hook_context):
    """Acknowledge local recorder completion, never durable backend persistence."""
    try:
        context = _thaw_frozen_json(hook_context)
        if type(context) is not dict:
            raise ValueError("invalid summary observer context")
        validated = build_summary_hook_context(**context)
        payload = _thaw_frozen_json(validated)["payload"]
        record_event(event_type="summary.hook.observed",
                     source="hooks.summary_events_observer", payload=payload, flush=True)
    except Exception:
        logger.warning("summary_hook_event_record_failed")
        return {"recorded": False}
    return {"recorded": True}
