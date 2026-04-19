"""
Unit tests for ai_base/agent_types/exception module.

Test coverage:
- AgentToolCallException
- AgentEndProcess
- AgentNoCareResult
- AgentFinalAnswer
- DataAgentRefreshSession
- AgentNeedRefreshSession
- ToolError

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock


class TestAgentToolCallException(unittest.TestCase):
    """Test cases for AgentToolCallException."""

    def test_exception_inherits_from_exception(self):
        """Test AgentToolCallException is a subclass of Exception."""
        from topsailai.ai_base.agent_types.exception import AgentToolCallException
        
        self.assertTrue(issubclass(AgentToolCallException, Exception))

    def test_exception_can_be_raised(self):
        """Test exception can be raised with a message."""
        from topsailai.ai_base.agent_types.exception import AgentToolCallException
        
        with self.assertRaises(AgentToolCallException):
            raise AgentToolCallException("Test error")


class TestAgentEndProcess(unittest.TestCase):
    """Test cases for AgentEndProcess exception."""

    def test_inherits_from_agent_tool_call_exception(self):
        """Test AgentEndProcess is a subclass of AgentToolCallException."""
        from topsailai.ai_base.agent_types.exception import AgentEndProcess, AgentToolCallException
        
        self.assertTrue(issubclass(AgentEndProcess, AgentToolCallException))

    def test_can_be_raised(self):
        """Test exception can be raised."""
        from topsailai.ai_base.agent_types.exception import AgentEndProcess
        
        with self.assertRaises(AgentEndProcess):
            raise AgentEndProcess("Process ended")


class TestAgentNoCareResult(unittest.TestCase):
    """Test cases for AgentNoCareResult exception."""

    def test_inherits_from_agent_tool_call_exception(self):
        """Test AgentNoCareResult is a subclass of AgentToolCallException."""
        from topsailai.ai_base.agent_types.exception import AgentNoCareResult, AgentToolCallException
        
        self.assertTrue(issubclass(AgentNoCareResult, AgentToolCallException))


class TestAgentFinalAnswer(unittest.TestCase):
    """Test cases for AgentFinalAnswer exception."""

    def test_inherits_from_agent_tool_call_exception(self):
        """Test AgentFinalAnswer is a subclass of AgentToolCallException."""
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer, AgentToolCallException
        
        self.assertTrue(issubclass(AgentFinalAnswer, AgentToolCallException))

    def test_can_carry_final_answer_message(self):
        """Test exception can carry the final answer."""
        from topsailai.ai_base.agent_types.exception import AgentFinalAnswer
        
        answer = "This is the final answer"
        with self.assertRaises(AgentFinalAnswer) as context:
            raise AgentFinalAnswer(answer)
        self.assertEqual(str(context.exception), answer)


class TestAgentNeedRefreshSession(unittest.TestCase):
    """Test cases for AgentNeedRefreshSession exception."""

    def test_inherits_from_agent_tool_call_exception(self):
        """Test AgentNeedRefreshSession is a subclass of AgentToolCallException."""
        from topsailai.ai_base.agent_types.exception import AgentNeedRefreshSession, AgentToolCallException
        
        self.assertTrue(issubclass(AgentNeedRefreshSession, AgentToolCallException))


class TestToolError(unittest.TestCase):
    """Test cases for ToolError exception."""

    def test_inherits_from_exception(self):
        """Test ToolError is a subclass of Exception."""
        from topsailai.ai_base.agent_types.exception import ToolError
        
        self.assertTrue(issubclass(ToolError, Exception))

    def test_can_be_raised_with_message(self):
        """Test exception can be raised with a message."""
        from topsailai.ai_base.agent_types.exception import ToolError
        
        with self.assertRaises(ToolError):
            raise ToolError("Tool execution failed")


class TestDataAgentRefreshSession(unittest.TestCase):
    """Test cases for DataAgentRefreshSession class."""

    def test_initialization_with_tool_result_and_session_id(self):
        """Test initialization with tool result and session ID."""
        from topsailai.ai_base.agent_types.exception import DataAgentRefreshSession
        
        data = DataAgentRefreshSession("tool result", "session123")
        
        self.assertEqual(data.tool_result, "tool result")
        self.assertEqual(data.session_id, "session123")
        self.assertEqual(data.tool_request, "")
        self.assertIsNone(data.ai_agent)
        self.assertIsNone(data._ctx_runtime_data)

    def test_initialization_with_none_values(self):
        """Test initialization with None values."""
        from topsailai.ai_base.agent_types.exception import DataAgentRefreshSession
        
        data = DataAgentRefreshSession(None, None)
        
        self.assertIsNone(data.tool_result)
        self.assertIsNone(data.session_id)

    def test_ctx_runtime_data_returns_none_when_no_agent(self):
        """Test ctx_runtime_data returns None when ai_agent is None."""
        from topsailai.ai_base.agent_types.exception import DataAgentRefreshSession
        
        data = DataAgentRefreshSession("result", "session123")
        # ai_agent is None by default
        result = data.ctx_runtime_data
        self.assertIsNone(result)

    def test_ctx_runtime_data_returns_none_when_no_session_id(self):
        """Test ctx_runtime_data returns None when session_id is None."""
        from topsailai.ai_base.agent_types.exception import DataAgentRefreshSession
        
        data = DataAgentRefreshSession("result", None)
        data.ai_agent = MagicMock()
        result = data.ctx_runtime_data
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
