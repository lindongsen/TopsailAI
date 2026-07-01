"""Pre-run hook that installs an agent-runtime input function.

This hook is discovered by ``workspace/agent/hooks/base/init.py`` and executed
before each agent run. It registers ``input_on_agent_runtime`` in thread-local
storage so that ``ai_base`` code can fall back to the workspace input tool
instead of the builtin ``input()``.
"""

from topsailai.utils.thread_local_tool import set_agent_runtime_input
from topsailai.workspace.input_tool import input_one_line


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

    set_agent_runtime_input(input_on_agent_runtime)


HOOKS = dict(
    pre_run_set_agent_runtime_input=pre_run_set_agent_runtime_input,
)
