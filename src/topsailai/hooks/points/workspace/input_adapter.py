"""Read-only input observation through application-scoped Hook authority.

Author: DawsonLin
"""

import logging

from topsailai.hooks.application_access import get_hook_executor
from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.contracts import DispatchReport, HookStatus
from topsailai.hooks.points.workspace.before_input_message import POINT

logger = logging.getLogger(__name__)


def observe_before_input(*, multiline: bool) -> None:
    """Dispatch once and isolate ordinary failures without handling host interrupts."""
    operation = HookOperation()
    try:
        executor = get_hook_executor()
        report = executor.dispatch(
            POINT, payload={"multiline": multiline}, operation=operation,
        )
        if type(report) is not DispatchReport:
            logger.warning("Input before Hook returned an invalid report operation=%s",
                           operation.operation_id)
            return
        if (report.rejection_reason is not None or report.deadline_exhausted
                or any(item.status != HookStatus.SUCCESS for item in report.outcomes)):
            logger.warning("Input before Hook did not fully succeed operation=%s point=%s",
                           operation.operation_id, POINT.name)
    except Exception:
        # Exception text and locals may contain sensitive plugin or input data.
        logger.warning("Input before Hook dispatch failed operation=%s point=%s",
                       operation.operation_id, POINT.name)
