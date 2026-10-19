"""Execute staged control actions on the existing wait coordinator thread."""
import os

from topsailai.ai_base.exception import HardInterruptError
from topsailai.ai_base.llm_control.control_runtime import consume_retry, LLMRequestedRetryError
from topsailai.hooks.control_signal import HookControlSignal
from topsailai.utils import env_tool
from topsailai.utils.thread_local_tool import get_agent_object


def main(**kwargs):
    """Check generic interruption first, then consume current-request retry."""
    agent = get_agent_object()
    if agent is None:
        return
    try:
        agent._check_hard_interrupt()
        if consume_retry(env_tool.get_session_id() or "topsailai", os.getpid()):
            raise LLMRequestedRetryError("Retry requested via control channel")
    except (HardInterruptError, LLMRequestedRetryError) as error:
        raise HookControlSignal(error) from error
