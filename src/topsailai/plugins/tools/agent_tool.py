"""Optional assistant tools; author: DawsonLin."""

from topsailai.tools.agent_tool_utils.writer import agent_writer, agent_programmer
from topsailai.tools.agent_tool_utils.multitasks import async_multitasks_agent_writer2

TOOLS = dict(
    WritingAssistant=agent_writer,
    ProgrammingAssistant=agent_programmer,
    WritingAssistantMultiTasks=async_multitasks_agent_writer2,
)

PROMPT = """
# About agent_tool (assistant)
Unless the user explicitly includes the word "assistant" (or phrases such as "call the assistant" or "use an assistant") in their request, you must not invoke, delegate, or imply any third-party assistant/agent_tool to perform the task. All responses must be generated solely by you.
"""

FLAG_TOOL_ENABLED = False
