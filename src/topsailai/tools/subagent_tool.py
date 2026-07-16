'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-14
  Purpose:
'''

import os
import re

from topsailai.logger import logger
from topsailai.utils.env_tool import (
    EnvReaderInstance,
)
from topsailai.prompt_hub import prompt_tool
from topsailai.context.common import get_session_id
from topsailai.workspace.task import task_tool
from topsailai.workspace.folder_constants import FOLDER_ROOT


DEFAULT_SUBAGENT_ROLE_FOLDER = os.path.join(FOLDER_ROOT, "subagents")
SUBAGENT_ROLE_FILE_PATTERN = re.compile(r"^(?P<name>[^.]+)\.member$")


# key is member name, value is agent instance
g_subagents = {}


def _get_subagent_role_folder() -> str:
    """Resolve the folder that contains subagent role definition files.

    Reads ``TOPSAILAI_SUBAGENT_ROLE_FOLDER``. When unset or empty, falls back
    to ``{TOPSAILAI_HOME}/subagents``.

    Returns:
        str: Absolute path to the role folder.
    """
    folder = EnvReaderInstance.get("TOPSAILAI_SUBAGENT_ROLE_FOLDER", "")
    if not folder:
        folder = DEFAULT_SUBAGENT_ROLE_FOLDER
    folder = os.path.expanduser(folder)
    return os.path.abspath(folder)


def _discover_subagent_roles(folder: str) -> dict[str, str]:
    """Discover and load subagent role definitions from a folder.

    Scans ``folder`` for files matching ``*.member`` and returns a
    mapping from role name to file content. Roles are sorted alphabetically to
    keep prompt construction deterministic.

    Args:
        folder: Path to the role folder.

    Returns:
        dict[str, str]: Mapping of role name -> role markdown content.
    """
    roles: dict[str, str] = {}
    if not os.path.isdir(folder):
        logger.debug("subagent role folder does not exist: %s", folder)
        return roles

    for entry in sorted(os.listdir(folder)):
        match = SUBAGENT_ROLE_FILE_PATTERN.match(entry)
        if not match:
            continue
        name = match.group("name")
        file_path = os.path.join(folder, entry)
        content = EnvReaderInstance.try_read_file(file_path)
        if content:
            roles[name] = content
    return roles


def _escape_role_content(content: str) -> str:
    """Wrap role content in a markdown code fence to avoid nesting issues.

    Role files may contain markdown headings, lists, or other formatting that
    would break the main tool prompt's own markdown structure. Wrapping the
    content in a fenced code block renders it verbatim. The fence length is
    chosen to be longer than any run of backticks in the content.

    Args:
        content: Raw role file content.

    Returns:
        str: Role content wrapped in a markdown code fence.
    """
    max_ticks = 0
    current = 0
    for ch in content:
        if ch == "`":
            current += 1
            max_ticks = max(max_ticks, current)
        else:
            current = 0
    fence = "`" * max(max_ticks + 1, 3)
    return f"{fence}text\n{content}\n{fence}"


def _build_role_catalog(roles: dict[str, str]) -> str:
    """Build a markdown catalog of available subagent roles.

    The catalog is split into two sections to keep the prompt readable even
    when role definition files contain markdown formatting:

    1. ``## Available Subagent Roles`` lists only the role names.
    2. ``## Subagent Role Details`` contains each role's full
       ``{role}.member`` definition wrapped in a fenced code block to prevent
       markdown nesting.

    Args:
        roles: Mapping of role name -> role markdown content.

    Returns:
        str: Markdown sections describing available subagents and their roles.
    """
    if not roles:
        return ""

    sorted_names = sorted(roles)

    lines = [
        "",
        "## Available Subagent Roles",
        "",
        "You can delegate tasks to a specialized subagent by passing the ``role`` argument.",
        "",
    ]
    for name in sorted_names:
        lines.append(f"- ``{name}``")
    lines.append("")

    lines.append("## Subagent Role Details")
    lines.append("")
    for name in sorted_names:
        lines.append(f"### {name}")
        lines.append("")
        lines.append(_escape_role_content(roles[name]))
        lines.append("")
    return "\n".join(lines)


_SUBAGENT_ROLE_FOLDER = _get_subagent_role_folder()
_SUBAGENT_ROLES = _discover_subagent_roles(_SUBAGENT_ROLE_FOLDER)
_SUBAGENT_ROLE_CATALOG = _build_role_catalog(_SUBAGENT_ROLES)


def gen_task_id():
    """
    Generate a new unique task ID and set it as an environment variable.

    This function generates a new task ID using the task_tool module, stores it
    in the TOPSAILAI_TASK_ID environment variable, and logs the generation.

    Returns:
        str: The newly generated task ID.
    """
    task_id = task_tool.generate_task_id()
    os.environ["TOPSAILAI_TASK_ID"] = task_id
    logger.info("generate new task id: [%s]", task_id)
    return task_id


def get_task_id():
    """
    Get the current task ID from environment or generate a new one.

    This function retrieves the task ID from the TOPSAILAI_TASK_ID environment
    variable. If no task ID exists, it generates a new one by calling gen_task_id().

    Returns:
        str: The current task ID (existing or newly generated).
    """
    task_id = os.getenv("TOPSAILAI_TASK_ID")
    if task_id:
        return task_id
    return gen_task_id()


def call_assistant(task:str, role:str=None, llm:str=None) -> str:
    """
    This is a versatile AI assistant. Leave everything you can't solve to it.

    [Trigger] When encountering difficulties(example: available tools are limited), DONOT ask the user, but call this assistant tool to solve them.
    **Everything you cannot, you JUST delegate to the assistant tool**

    Args:
        task (str): content
        role (str, optional): subagent role/member name
        llm (str, optional): large language model

    Returns:
        str: final_answer
    """
    assert task, "missing task content"

    if role:
        if role.endswith(".member"):
            role = role[:-len(".member")]
        assert role in _SUBAGENT_ROLES, f"invalid role: [{role}]"

    role_name = role
    agent_name = role_name or os.getenv("TOPSAILAI_AGENT_NAME") or "Agent"
    suffix = f".{llm}" if llm else ""
    agent_name = f"Sub.{agent_name}{suffix}"

    from topsailai.workspace.agent_shell import get_agent_chat

    disabled_tools = ["agent_tool", "subagent_tool"]

    system_prompt = f"""
## Sub Agent
I am a sub-agent, and my name is ({role_name or agent_name})
"""
    system_prompt += EnvReaderInstance.read_file_or_content("TOPSAILAI_SUBAGENT_SYSTEM_PROMPT")

    message = task
    if role:
        role_content = _SUBAGENT_ROLES.get(role)
        assert role_content, f"role content missing: [{role}]"
        system_prompt += "\n\n" + role_content
        message = f"@{role}:\n{task}"

    task_agent = g_subagents.get(agent_name)
    if task_agent is None:
        task_agent = get_agent_chat(
            system_prompt=system_prompt,
            disabled_tools=disabled_tools,
            need_input_message=False,
            agent_name=agent_name,
            need_set_agent_name_to_thread_local=False,
            need_project_workspace_lock=False,
        )
        g_subagents[agent_name] = task_agent

    # init agent
    task_agent.reset(
        first_message=message,
        model_name=llm,
    )

    task_id = get_task_id()
    try:
        return task_agent._run(
            message=message,
            times=1,
            need_session_lock=False,
            task_id=task_id,
        )
    finally:
        del task_agent


class MainAgent(object):
    """ Main Agent Object """
    def __init__(self, agent_name=None):
        if not agent_name:
            agent_name = os.getenv("TOPSAILAI_AGENT_NAME") or "Agent"

        self.agent_name = agent_name
        self.system_prompt = """
## Main(Manager) & Sub(Member) Agents
I am Main-Agent(Manager)

> Manager Role & Constraint
> Manager is a "Router and Coordinator". Not an Executor.
> Manager subdivide the tasks to ensure that the tasks assigned to each member are detailed, focused, as simple and clear as possible.
"""

        # Tool availability for the plan_agent:
        #
        # `enabled_tools` acts as an explicit allow-list. Only the tool kits listed
        # below are available to the plan_agent, plus any tools injected via
        # `tool_map`.
        #
        # Available tools:
        #   - file_readonly_tool-* (read-only file operations, injected by get_tool_map)
        #       - check_files_existing
        #       - get_file_size
        #       - list_dirs
        #       - read_file
        #       - read_file_around_line
        #       - read_file_lines
        #       - read_file_with_context
        #       - read_files
        #   - story_memory_tool-* (persistent memory access)
        #   - subagent_tool-call_assistant (delegate work to sub-agents)
        #
        # Deliberately unavailable:
        #   - agent_tool is disabled via disabled_tools.
        #   - cmd_tool, file_tool (write variants), skill_tool, time_tool, ctx_tool,
        #     and all other internal tools are NOT in the allow-list, so the main
        #     agent cannot execute commands, write files, call skills, etc. directly.
        #     Any such action must be delegated to a sub-agent through
        #     subagent_tool-call_assistant.
        #
        # Determine whether to inject the read-only file tool map into the plan
        # agent. This is controlled by the TOPSAILAI_AGENT_PLAN_USE_TOOL_MAP
        # environment variable. When set to a truthy value (e.g. "1", "true", "yes",
        # "on", "enabled"), the file_readonly_tool-* handlers are passed via
        # tool_map. When unset or falsy, tool_map is omitted and the plan agent only
        # has access to the story_memory_tool and subagent_tool kits.
        self.use_tool_map = EnvReaderInstance.check_bool("TOPSAILAI_AGENT_PLAN_USE_TOOL_MAP")

        self.plan_agent_kwargs = dict(
            system_prompt=self.system_prompt,
            session_id=get_session_id(),
            disabled_tools=["agent_tool"],
            enabled_tools=["story_memory_tool", "subagent_tool"],
            agent_type="plan_and_execute",
        )
        if self.use_tool_map:
            self.plan_agent_kwargs["tool_map"] = self.tool_map

        # agent
        from topsailai.workspace.agent_shell import get_agent_chat
        # plan agent
        self.plan_agent = get_agent_chat(**self.plan_agent_kwargs)
        self.run = self.plan_agent.run

        return

    @property
    def tool_map(self) -> dict:
        """
        Build and return a mapping of tool names to their corresponding functions.

        This function constructs a dictionary that maps tool names to their handler
        functions. It includes the plan_tool-call_assistant function and all file
        readonly tools. Each tool is also registered using the add_tool function.

        Returns:
            dict: A dictionary mapping tool names (str) to their handler functions.
        """
        from topsailai.tools import (
            file_readonly_tool,
        )
        tool_map = {}
        for tool_name, tool_func in file_readonly_tool.FILE_RO_TOOLS.items():
            tool_name = "file_readonly_tool-" + tool_name
            tool_map[tool_name] = tool_func

        return tool_map


def init_doc():
    models = EnvReaderInstance.get_list_str("TOPSAILAI_SUBAGENT_TOOL_AVAILABLE_LLMS", separator="")
    if models:
        call_assistant.__doc__ += f"\nSupported LLM: {models}\n"

    from topsailai.tools import (
        skill_tool,
    )

    if skill_tool.PROMPT_PLUGIN_SKILLS:
        call_assistant.__doc__ += "\n>>> SKILL START\n" + skill_tool.PROMPT_PLUGIN_SKILLS + "\n<<< SKILL END"

    return

init_doc()
TOOLS = dict(
    call_assistant=call_assistant,
)

FLAG_TOOL_ENABLED = False

PROMPT = prompt_tool.read_prompt("work_mode/sop/collaboration.md") + \
    EnvReaderInstance.read_file_or_content("TOPSAILAI_SUBAGENT_TOOL_PROMPT") + \
    _SUBAGENT_ROLE_CATALOG
