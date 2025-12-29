from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_error,
    print_step,
)
from topsailai.utils.thread_local_tool import (
    ctxm_give_agent_name,
    ctxm_set_agent,
)
from topsailai.utils import (
    json_tool,
    env_tool,
)

from topsailai.ai_base.prompt_base import (
    PromptBase,
)
from topsailai.ai_base.llm_base import (
    LLMModel,
)
from topsailai.prompt_hub import prompt_tool

from topsailai.tools import (
    get_tool_prompt,
    TOOLS as INTERNAL_TOOLS,
    get_tools_for_chat,
)


class ToolCallInfo(object):
    def __init__(self):
        self.func_name = ""
        self.func_args = {}


class StepCallBase(object):
    """ the datastructure of return value of step_call(...) """
    CODE_TASK_FINAL = 0
    CODE_STEP_FINAL = 1
    CODE_TASK_FAILED = -1

    def __init__(self, flag_interactive:bool=False):

        # for result
        self.code = None
        self.user_msg = None
        self.tool_msg = None
        self.result = None

        # flags
        self.flag_interactive = True if flag_interactive else False

        return

    def __call__(self, *args, **kwds):
        # it must init all of result for each call
        self.__init__()
        self._execute(*args, **kwds)
        return self

    def get_tool_call_info(self, step:dict, rsp_msg_obj) -> ToolCallInfo|None:
        """Get tool call information.

        Args:
            step (dict): it is from message info
            rsp_msg_obj: a instance for chatMessage

        Returns:
            dict|None:
              func_name (str):
              func_args (dict):
        """
        if rsp_msg_obj is not None:
            # list_dict
            tool_calls = rsp_msg_obj.tool_calls
            if tool_calls:
                tool_call = tool_calls[0]

                func_name = tool_call.function.name
                func_args = None
                if tool_call.function.arguments:
                    try:
                        func_args = json_tool.json_load(tool_call.function.arguments)
                    except Exception as e:
                        logger.exception(e)
                        return None

                if func_name:
                    result = ToolCallInfo()
                    result.func_name = func_name
                    result.func_args = func_args or {}
                    return result

        if 'tool_call' in step:
            func_name = step["tool_call"]
            func_args = step.get('tool_args')

            if func_name:
                result = ToolCallInfo()
                result.func_name = func_name
                result.func_args = func_args or {}
                return result

        if 'raw_text' in step:
            try:
                raw_text = json_tool.convert_code_block_to_json_str(step["raw_text"]) or step["raw_text"]
                raw_text = json_tool.to_json_str(raw_text)
                raw_dict = None
                if raw_text:
                    raw_dict = json_tool.json_load(raw_text)
                if raw_dict and 'tool_call' in raw_dict:
                    func_name = raw_dict['tool_call']
                    func_args = raw_dict.get('tool_args')
                    if func_name:
                        result = ToolCallInfo()
                        result.func_name = func_name
                        result.func_args = func_args or {}
                        return result
            except Exception:
                pass

        return None

    def _execute(
            self,
            step:dict,
            tools:dict,
            response:list,
            index:int,
            rsp_msg_obj=None,
        ):
        """ override this method """
        raise NotImplementedError("Subclasses must implement this method")

class AgentBase(PromptBase):
    """ AI-Agent base class """
    def __init__(
            self,
            system_prompt:str,
            tools:dict,
            agent_name:str,
            tool_prompt:str="",
            tool_kits:list=None,
            excluded_tool_kits:list=None,
        ):
        """
        :tools: dict, the specific tools, key is tool_name, value is function;
        :tool_kits: list, the internal tools list, [name1, name2];
        """
        self.system_prompt = system_prompt
        self.tools = tools
        self.agent_name = agent_name
        assert self.system_prompt, "system_prompt is required"

        self.llm_model = LLMModel()

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
        self.available_tools = dict()
        for tool_name in tool_kits or []:
            self.available_tools[tool_name] = INTERNAL_TOOLS[tool_name]
        for tool_name in self.tools or {}:
            self.available_tools[tool_name] = self.tools[tool_name]

        ######################################################################
        # tool prompts
        ######################################################################
        if not tool_prompt:
            tool_prompt = ""

        if self.available_tools:
            if not env_tool.is_use_tool_calls():
                # get tool docs as prompt
                tool_prompt += get_tool_prompt(None, self.available_tools)

            # extend prompt with tool
            tool_prompt += prompt_tool.get_prompt_by_tools(self.available_tools)

            # extra tools
            tool_prompt += prompt_tool.get_extra_tools()

        # prepare tool_prompt ok
        self.tool_prompt = tool_prompt

        # debug
        if self.tool_prompt:
            print_step(f"[tool_prompt]:\n{self.tool_prompt}\n", need_format=False)

        super(AgentBase, self).__init__(self.system_prompt, self.tool_prompt)
        return

    @property
    def max_tokens(self) -> int:
        """ get max tokens """
        return self.llm_model.max_tokens

    @property
    def all_tools(self):
        """ return all of available tools. include of internal tools. """
        all_tools = {}
        # first, internal tools
        all_tools.update(INTERNAL_TOOLS)

        # second, specific tools for this agent.
        if self.tools:
            all_tools.update(self.tools)

        return all_tools

    def run(self, step_call:StepCallBase, user_input:str):
        """ run this agent """
        with (
                ctxm_give_agent_name(self.agent_name),
                ctxm_set_agent(self),
            ):
            try:
                return self._run(step_call, user_input)
            finally:
                if self.flag_dump_messages:
                    self.dump_messages()

    def _run(self, step_call:StepCallBase, user_input:str):
        raise NotImplementedError("Subclasses must implement this method")

class AgentRun(AgentBase):
    """ a common of running steps """
    def _run(self, step_call:StepCallBase, user_input:str):
        """ return final answer, or None if error """
        # tools
        all_tools = self.available_tools
        print_step(f"[available_tools] [{len(all_tools)}] {list(all_tools.keys())}", need_format=False)

        tools_for_chat = {}
        if env_tool.is_use_tool_calls():
            tools_for_chat = get_tools_for_chat(all_tools)
        if tools_for_chat:
            print_step(f"[effective_tools] [{len(tools_for_chat)}] {list(tools_for_chat.keys())}", need_format=False)

        # new session
        if user_input:
            self.new_session({"step_name":"task","raw_text":user_input})

        while True:
            rsp_obj, response = self.llm_model.chat(
                self.messages, for_response=True,
                for_stream=env_tool.EnvReaderInstance.check_bool("LLM_RESPONSE_STREAM"),
                tools=list(tools_for_chat.values()),
            )
            if not response:
                print_error("No response from LLM.")
                return None
            rsp_msg = self.llm_model.get_response_message(rsp_obj)
            self.add_assistant_message(response, tool_calls=rsp_msg.tool_calls)

            ctx_count = len(self.messages)

            for i, step in enumerate(response):
                ret = step_call(step, tools=all_tools, response=response, index=i, rsp_msg_obj=rsp_msg)
                assert isinstance(ret, StepCallBase), "step_call must return StepCallBase instance"
                if ret.code == ret.CODE_TASK_FINAL:
                    logger.info(f"final: {ret.result}")
                    return ret.result
                elif ret.code == ret.CODE_TASK_FAILED:
                    print_error(f"Task failed: {ret.result}")
                    return None
                elif ret.code == ret.CODE_STEP_FINAL:
                    self.add_user_message(ret.user_msg)
                    self.add_tool_message(ret.tool_msg)
                    break

            # end for step in response

            if len(self.messages) == ctx_count:
                print_error("No progress made in this iteration, exiting.")
                return None

            # update env
            self.update_message_for_env()

        # raise RuntimeError("Unreachable code reached")
