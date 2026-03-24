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

# error
class ToolError(Exception):
    pass
