'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-25
  Purpose:
'''

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
)
from topsailai.utils.print_tool import (
    print_step,
)
from topsailai.ai_base.prompt_base import PromptBase
from topsailai.prompt_hub import prompt_tool
from topsailai.tools.base.init import (
    TOOLS as INTERNAL_TOOLS,
)
from topsailai.tools.base.common import (
    get_tools_by_module,
    add_tool,
)


class AgentTool(PromptBase):

    def __init__(
            self,
            system_prompt,
            tool_prompt = "",
            tools:dict=None,
            tool_kits:list=None,
            excluded_tool_kits:list=None,
        ):
        # Specific tools for this agent
        self.tools = tools
        self.available_tools = {}

        self.tool_prompt_raw = tool_prompt

        ######################################################################
        # tool_kits, internal tools
        ######################################################################
        if not self.tools and not tool_kits:
            # using all of internal tools.
            tool_kits = list(INTERNAL_TOOLS.keys())

        if tool_kits and excluded_tool_kits:
            for tool_name in excluded_tool_kits:
                if tool_name in tool_kits:
                    tool_kits.remove(tool_name)
                    continue
                for _tool in tool_kits[:]:
                    if _tool.startswith(tool_name):
                        if _tool in tool_kits:
                            tool_kits.remove(_tool)

        if tool_kits:
            tool_kits = prompt_tool.get_tools_by_env(tool_kits)

        ######################################################################
        # all of available tools
        ######################################################################
        # Dictionary of all available tools for this agent
        self.available_tools = dict()
        for tool_name in tool_kits or []:
            for _internal_tool_name in INTERNAL_TOOLS.keys():
                if _internal_tool_name.startswith(tool_name):
                    self.available_tools[_internal_tool_name] = INTERNAL_TOOLS[_internal_tool_name]

        for tool_name in self.tools or {}:
            self.available_tools[tool_name] = self.tools[tool_name]

        ######################################################################
        # tool prompts
        ######################################################################
        self.generate_tool_prompt()

        super().__init__(system_prompt, self.tool_prompt)

    @property
    def all_tools(self):
        """
        Get all available tools including internal tools.

        Returns:
            dict: Dictionary containing all available tools
        """
        # Dictionary to store all tools
        all_tools = {}
        # first, internal tools
        all_tools.update(INTERNAL_TOOLS)

        # second, specific tools for this agent.
        if self.tools:
            all_tools.update(self.tools)

        return all_tools

    def remove_tools(self, tool_name:str) -> int:
        """ Remove tools by name or prefix

        Args:
            tool_name (str):

        Returns:
            int: number of tools were removed
        """
        if not tool_name:
            return 0
        count = 0
        for avail_tool_name in list(self.available_tools.keys()):
            if avail_tool_name.startswith(tool_name):
                count += 1
                del self.available_tools[avail_tool_name]
                logger.info("remove tool: [%s]", avail_tool_name)
        return count

    def add_tool(self, tool_name, tool_func) -> bool:
        """ add a tool """
        if tool_name in self.available_tools:
            logger.warning("tool was existed, no need add it: [%s]", tool_name)
            return False
        self.available_tools[tool_name] = tool_func
        add_tool(tool_name, tool_func)
        logger.info("add tool: [%s] [%s]", tool_name, tool_func)
        return True

    def add_tools(self, tool_map:dict) -> dict:
        """ add tools """
        result = {}
        for tool_name, tool_func in tool_map.items():
            result[tool_name] = self.add_tool(tool_name, tool_func)
        return result

    def add_tools_by_module(self, module_path:str) -> dict:
        """ add tools by module import """
        tool_map = get_tools_by_module(module_path)
        result = self.add_tools(tool_map)
        return result

    def reload_tool_prompt(self):
        """ reload tool prompt to message """
        self.generate_tool_prompt(True)
        self.update_message_for_tool()
        return

    def generate_tool_prompt(self, need_reload=False):
        """ generate final tool prompt """
        tool_prompt = self.tool_prompt_raw or ""

        if self.available_tools:
            tool_prompt += prompt_tool.generate_prompt_by_tools(
                self.available_tools,
                need_reload=need_reload,
            )

        # prepare tool_prompt ok
        # Tool prompt text for the agent
        self.tool_prompt = tool_prompt

        # debug
        if self.tool_prompt \
            and env_tool.EnvReaderInstance.check_bool("TOPSAILAI_PRINT_TOOL_PROMPT") \
            and env_tool.is_interactive_mode():
            print_step(f"[tool_prompt]:\n{self.tool_prompt}\n", need_format=False)

        return self.tool_prompt
