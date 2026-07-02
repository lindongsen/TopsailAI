"""Pre-run hook that installs an agent-runtime input function.

This hook is discovered by ``workspace/agent/hooks/base/init.py`` and executed
before each agent run. It registers ``input_on_agent_runtime`` in thread-local
storage so that ``ai_base`` code can fall back to the workspace input tool
instead of the builtin ``input()``.
"""

from topsailai.utils import env_tool
from topsailai.utils.thread_local_tool import (
    set_agent_runtime_input,
    set_agent_runtime_input_with_timeout,
)
from topsailai.workspace.input_tool import input_from_pipe_session, input_one_line


def pre_run_set_agent_runtime_input(self):
    """Register ``input_on_agent_runtime`` for the current agent run.

    The wrapper uses the agent's ``hook_instruction`` instance so that ``/``
    commands and TAB completions work consistently with interactive chat.

    Args:
        self: The current ``AgentChat`` instance.
    """
    hook = self.hook_instruction

    def input_on_agent_runtime(tips: str = "", hook=hook):
        """Agent-runtime input wrapper around ``input_one_line``.

        Args:
            tips: Optional prompt text passed to ``input_one_line``.
            hook: ``HookInstruction`` instance used for command interception.

        Returns:
            The string returned by ``input_one_line``.
        """
        return input_one_line(tips=tips, hook=hook)

    def input_on_agent_runtime_with_timeout(
        tips: str = "", timeout: float | None = None, hook=hook
    ):
        """Agent-runtime input wrapper that reads from the session pipe.

        Args:
            tips: Optional prompt text displayed while waiting for input.
            timeout: Maximum time in seconds to wait for pipe input.
            hook: ``HookInstruction`` instance captured from the agent chat.

        Returns:
            The string returned by ``input_from_pipe_session``.
        """
        return input_from_pipe_session(
            session_id=env_tool.get_session_id(),
            single_line=True,
            timeout=timeout,
            prompt=tips,
        )

    set_agent_runtime_input(input_on_agent_runtime)
    set_agent_runtime_input_with_timeout(input_on_agent_runtime_with_timeout)


HOOKS = dict(
    pre_run_set_agent_runtime_input=pre_run_set_agent_runtime_input,
)
