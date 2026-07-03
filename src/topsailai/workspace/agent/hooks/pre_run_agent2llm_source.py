"""Pre-run hook that installs an Agent2LLM runtime message source.

This hook is discovered by ``workspace/agent/hooks/base/init.py`` and executed
before each agent run. It registers a concrete
``Agent2LLMMessageSource`` implementation (e.g. file-based) in thread-local
storage so that ``ai_base`` can inject runtime messages before each LLM call.
"""

import logging

from topsailai.utils import env_tool
from topsailai.ai_base.agent2llm_message_source import set_agent2llm_message_source
from topsailai.workspace.agent.runtime_message_sources import create_source
from topsailai.workspace.agent.runtime_message_sources.file import (
    get_default_inject_message_file_path,
)

logger = logging.getLogger(__name__)


def pre_run_set_agent2llm_message_source(self):
    """Register an Agent2LLM message source for the current agent run.

    The source type and configuration are read from environment variables.
    When disabled or the source type is unknown, the thread-local source is
    left unset.

    Args:
        self: The current ``AgentChat`` instance (unused but kept for hook
            signature consistency).
    """
    enabled = env_tool.EnvReaderInstance.check_bool(
        "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED", default=False
    )
    if not enabled:
        return

    source_type = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE", default="file"
    )
    file_path = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE", default=""
    )
    if not file_path:
        file_path = get_default_inject_message_file_path()

    source = create_source(source_type, {"file_path": file_path})
    if source is None:
        logger.warning("unknown Agent2LLM inject message source type [%s]", source_type)
        return

    set_agent2llm_message_source(source)


HOOKS = dict(
    pre_run_set_agent2llm_message_source=pre_run_set_agent2llm_message_source,
)
