"""Unit tests for the typed agent runtime facade.

Author: DawsonLin
"""

import gc
from types import SimpleNamespace
import weakref

import pytest

from topsailai.ai_base.agent_runtime import AgentRuntime
from topsailai.context.tool_stat import ToolStat


class FakeAgent:
    """Provide the attributes required by AgentRuntime without AgentBase."""

    def __init__(self) -> None:
        """Initialize fake runtime components."""
        self.llm_model = SimpleNamespace(tokenStat=object(), max_tokens=4096)
        self.messages = []
        self.available_tools = {}
        self.llm_request_stat = object()
        self.state_visualizer = object()


def test_runtime_exposes_bound_agent_components() -> None:
    """Expose all runtime components through stable typed properties."""
    agent = FakeAgent()
    tool_stat = ToolStat()
    runtime = AgentRuntime(agent, tool_stat=tool_stat)

    assert runtime.agent is agent
    assert runtime.llm_model is agent.llm_model
    assert runtime.token_stat is agent.llm_model.tokenStat
    assert runtime.tool_stat is tool_stat
    assert runtime.agent2llm_messages is agent.messages
    assert runtime.available_tools is agent.available_tools
    assert runtime.llm_request_stat is agent.llm_request_stat
    assert runtime.state_visualizer is agent.state_visualizer
    assert runtime.max_tokens == 4096


def test_runtime_properties_follow_replaced_agent_components() -> None:
    """Resolve dynamic properties from the agent instead of cached snapshots."""
    agent = FakeAgent()
    runtime = AgentRuntime(agent)
    replacement_model = SimpleNamespace(tokenStat=object(), max_tokens=8192)
    replacement_messages = [{"role": "user", "content": "new context"}]
    replacement_tools = {"tool": object()}
    replacement_request_stat = object()
    replacement_visualizer = object()

    agent.llm_model = replacement_model
    agent.messages = replacement_messages
    agent.available_tools = replacement_tools
    agent.llm_request_stat = replacement_request_stat
    agent.state_visualizer = replacement_visualizer

    assert runtime.llm_model is replacement_model
    assert runtime.token_stat is replacement_model.tokenStat
    assert runtime.agent2llm_messages is replacement_messages
    assert runtime.available_tools is replacement_tools
    assert runtime.llm_request_stat is replacement_request_stat
    assert runtime.state_visualizer is replacement_visualizer
    assert runtime.max_tokens == 8192


def test_runtime_does_not_keep_agent_alive() -> None:
    """Fail clearly after the weakly referenced agent is released."""
    agent = FakeAgent()
    runtime = AgentRuntime(agent)
    agent_ref = weakref.ref(agent)

    del agent
    gc.collect()

    assert agent_ref() is None
    with pytest.raises(RuntimeError, match="no longer available"):
        _ = runtime.agent
