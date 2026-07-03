"""Runtime message source implementations for Agent2LLM injection.

This package contains concrete implementations of
``topsailai.ai_base.agent2llm_message_source.Agent2LLMMessageSource``. New
sources can be added here and registered in ``REGISTRY`` without modifying the
``ai_base`` injection logic.
"""

from topsailai.ai_base.agent2llm_message_source import Agent2LLMMessageSource
from topsailai.workspace.agent.runtime_message_sources.file import (
    FileAgent2LLMMessageSource,
)

REGISTRY = {
    "file": FileAgent2LLMMessageSource,
}


def create_source(source_type: str, config: dict) -> Agent2LLMMessageSource | None:
    """Create a runtime message source by type.

    Args:
        source_type: Source type name (e.g. ``"file"``).
        config: Keyword arguments passed to the source constructor.

    Returns:
        The configured source instance, or ``None`` if the type is unknown.
    """
    cls = REGISTRY.get(source_type)
    if cls is None:
        return None
    return cls(**config)
