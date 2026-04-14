'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-01-20
  Purpose:
'''

class AgentToolCallException(Exception):
    pass

# signal/info
class AgentEndProcess(AgentToolCallException):
    """ Force to abort execution of agent """
    pass

class AgentNoCareResult(AgentToolCallException):
    """ No care result of tool call """
    pass

class AgentFinalAnswer(AgentToolCallException):
    """ current step is final answer """
    pass


class DataAgentRefreshSession(object):
    def __init__(self, tool_result, session_id):

        # request message
        self.tool_request = ""

        # response message
        self.tool_result = tool_result

        self.session_id = session_id
        self.ai_agent = None

        self._ctx_runtime_data = None

    @property
    def ctx_runtime_data(self):
        if self._ctx_runtime_data is not None:
            return self._ctx_runtime_data

        if self.ai_agent is None:
            return None
        if self.session_id is None:
            return None

        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
        self._ctx_runtime_data = ContextRuntimeData()
        self._ctx_runtime_data.init(self.session_id, self.ai_agent)
        return self._ctx_runtime_data

class AgentNeedRefreshSession(AgentToolCallException):
    """ update session messages to agent.messages """
    pass

# error
class ToolError(Exception):
    pass
