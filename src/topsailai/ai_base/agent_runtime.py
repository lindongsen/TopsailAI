"""Typed access to runtime components owned by an agent."""

from typing import TYPE_CHECKING, Any
import weakref

from topsailai.context.tool_stat import ToolStat

if TYPE_CHECKING:
    from topsailai.ai_base.agent_base import AgentBase


class AgentRuntime:
    """Provide stable access to one agent's runtime components."""

    def __init__(
        self,
        agent: "AgentBase",
        tool_stat: ToolStat | None = None,
    ) -> None:
        """Bind the runtime facade to an agent without owning the agent."""
        self._agent_ref = weakref.ref(agent)
        self.tool_stat = tool_stat if tool_stat is not None else ToolStat()

    @property
    def agent(self) -> "AgentBase":
        """Return the bound agent or fail when it has been released."""
        agent = self._agent_ref()
        if agent is None:
            raise RuntimeError("The agent bound to this runtime is no longer available")
        return agent

    @property
    def llm_model(self) -> Any:
        """Return the agent's current LLM model."""
        return self.agent.llm_model

    @property
    def token_stat(self) -> Any:
        """Return token statistics from the agent's current LLM model."""
        return self.llm_model.tokenStat

    @property
    def llm_request_stat(self) -> Any:
        """Return the agent's current LLM request statistics."""
        return self.agent.llm_request_stat

    @property
    def state_visualizer(self) -> Any:
        """Return the agent's current LLM state visualizer."""
        return self.agent.state_visualizer

    @property
    def max_tokens(self) -> int:
        """Return the current LLM model's maximum token count."""
        return self.llm_model.max_tokens
