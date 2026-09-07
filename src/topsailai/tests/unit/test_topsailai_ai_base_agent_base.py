"""
Unit tests for ai_base/agent_base.py

Tests AgentBase and AgentRun classes.
"""

import unittest
from unittest.mock import MagicMock, patch

from topsailai.ai_base.llm_base import LLMModel as RealLLMModel


class TestAgentBaseInitialization(unittest.TestCase):
    """Test AgentBase initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.mock_llm_model.max_tokens = 4096
        
        self.patches = [
            patch('topsailai.ai_base.llm_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.get_tools_for_chat'),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_info'),
            patch('topsailai.ai_base.agent_base.ctxm_give_agent_name'),
            patch('topsailai.ai_base.agent_base.ctxm_set_agent'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_init_with_system_prompt_and_tools_and_agent_name(self):
        """Test basic initialization with required parameters."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )

        self.assertEqual(agent.agent_name, "TestAgent")
        self.assertEqual(agent.agent_type, "")
        self.assertEqual(agent.agent_role, "worker")

    def test_agent_injects_shared_runtime_components_into_llm_model(self):
        """Agent and model share the same request stat and visualizer instances."""
        from topsailai.ai_base.agent_base import AgentBase
        from topsailai.ai_base.llm_base import LLMModel

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent",
        )

        call_kwargs = LLMModel.call_args.kwargs
        self.assertIs(call_kwargs["llm_request_stat"], agent.llm_request_stat)
        self.assertIs(call_kwargs["state_visualizer"], agent.state_visualizer)

    def test_agents_own_isolated_runtime_components(self):
        """Separate agents never share request statistics or visualizers."""
        from topsailai.ai_base.agent_base import AgentBase

        first = AgentBase("prompt", {}, "first")
        second = AgentBase("prompt", {}, "second")

        self.assertIsNot(first.llm_request_stat, second.llm_request_stat)
        self.assertIsNot(first.state_visualizer, second.state_visualizer)

    def test_close_delegates_to_owned_llm_model(self):
        """Closing an agent closes its model-owned runtime components."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase("prompt", {}, "agent")
        agent.close()

        self.mock_llm_model.close.assert_called_once_with()

    def test_init_with_tool_prompt(self):
        """Test initialization with tool prompt."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent",
            tool_prompt="Additional tool instructions"
        )

        self.assertEqual(agent.agent_name, "TestAgent")

    def test_init_with_tool_kits(self):
        """Test initialization with tool kits."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent",
            tool_kits=["kit1", "kit2"]
        )

        self.assertEqual(agent.agent_name, "TestAgent")

    def test_init_with_excluded_tool_kits(self):
        """Test initialization with excluded tool kits."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent",
            excluded_tool_kits=["excluded_kit"]
        )

        self.assertEqual(agent.agent_name, "TestAgent")


class TestAgentBaseMaxTokens(unittest.TestCase):
    """Test AgentBase max_tokens property."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.mock_llm_model.max_tokens = 4096

        self.patches = [
            patch('topsailai.ai_base.llm_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_info'),
            patch('topsailai.ai_base.agent_base.ctxm_give_agent_name'),
            patch('topsailai.ai_base.agent_base.ctxm_set_agent'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_max_tokens_property(self):
        """Test max_tokens property returns LLM model value."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )

        self.assertEqual(agent.max_tokens, 4096)


class TestAgentBaseRun(unittest.TestCase):
    """Test AgentBase run method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.step_call_mock = MagicMock()

        self.patches = [
            patch('topsailai.ai_base.llm_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.get_tools_for_chat'),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_info'),
            patch('topsailai.ai_base.agent_base.ctxm_give_agent_name'),
            patch('topsailai.ai_base.agent_base.ctxm_set_agent'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_run_sets_context_and_calls_run(self):
        """Test run method sets context and calls internal _run."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(return_value="result")
        agent.flag_dump_messages = False

        result = agent.run(self.step_call_mock, "test input")

        self.assertEqual(result, "result")
        agent._run.assert_called_once_with(self.step_call_mock, "test input")

    def test_run_dumps_messages_when_flag_set(self):
        """Test run method dumps messages when flag is set."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(return_value="result")
        agent.dump_messages = MagicMock()
        agent.flag_dump_messages = True

        result = agent.run(self.step_call_mock, "test input")

        self.assertEqual(result, "result")
        agent.dump_messages.assert_called_once()

    def test_run_catches_exception_and_dumps_messages(self):
        """Test run method catches exception and still dumps messages."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(side_effect=Exception("Test error"))
        agent.dump_messages = MagicMock()
        agent.flag_dump_messages = True

        with self.assertRaises(Exception):
            agent.run(self.step_call_mock, "test input")

        agent.dump_messages.assert_called_once()

    def test_run_clears_pending_native_tool_calls_before_and_after_success(self):
        """Test run clears pending native tool calls around successful work."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        call_order = []
        agent.llm_model.clear_pending_native_tool_call_responses.side_effect = (
            lambda: call_order.append("clear")
        )
        agent._run = MagicMock(
            side_effect=lambda *args: call_order.append("run") or "result"
        )
        agent.flag_dump_messages = False

        result = agent.run(self.step_call_mock, "test input")

        self.assertEqual(result, "result")
        self.assertEqual(call_order, ["clear", "run", "clear"])

    def test_run_clears_pending_native_tool_calls_after_exception(self):
        """Test run clears pending native tool calls when work raises."""
        from topsailai.ai_base.agent_base import AgentBase

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        call_order = []
        agent.llm_model.clear_pending_native_tool_call_responses.side_effect = (
            lambda: call_order.append("clear")
        )

        def raise_error(*args):
            """Record execution before raising the test error."""
            call_order.append("run")
            raise RuntimeError("Test error")

        agent._run = MagicMock(side_effect=raise_error)
        agent.flag_dump_messages = False

        with self.assertRaises(RuntimeError):
            agent.run(self.step_call_mock, "test input")

        self.assertEqual(call_order, ["clear", "run", "clear"])

    def test_run_does_not_unset_agent2llm_message_source(self):
        """Test run does not unset the thread-local source when _run raises.

        The message source is owned by the User2Agent conversation layer and
        must survive across per-turn AgentBase.run calls. Cleanup belongs to
        the conversation loop, not the per-turn run.
        """
        from topsailai.ai_base.agent_base import AgentBase
        from topsailai.ai_base.agent2llm_message_source import (
            set_agent2llm_message_source,
            get_agent2llm_message_source,
            Agent2LLMMessageSource,
        )

        class DummySource(Agent2LLMMessageSource):
            def consume_messages(self):
                return []
            def produce_message(self, content, role="user", step_name="observation"):
                return True

        set_agent2llm_message_source(DummySource())
        self.assertIsNotNone(get_agent2llm_message_source())

        agent = AgentBase(
            system_prompt="You are a helpful assistant",
            tools={"tool1": MagicMock()},
            agent_name="TestAgent"
        )
        agent._run = MagicMock(side_effect=Exception("boom"))
        agent.flag_dump_messages = False

        with self.assertRaises(Exception):
            agent.run(self.step_call_mock, "test input")

        self.assertIsNotNone(get_agent2llm_message_source())

class TestAgentRunRunEdgeCases(unittest.TestCase):
    """Test AgentRun._run edge cases with proper setup."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_llm_model = MagicMock()
        self.step_call_mock = MagicMock()

        self.patches = [
            patch('topsailai.ai_base.llm_base.LLMModel', return_value=self.mock_llm_model),
            patch('topsailai.ai_base.agent_base.AgentTool.__init__', return_value=None),
            patch('topsailai.ai_base.agent_base.get_tools_for_chat'),
            patch('topsailai.ai_base.agent_base.logger'),
            patch('topsailai.ai_base.agent_base.print_critical'),
            patch('topsailai.ai_base.agent_base.print_info'),
            patch('topsailai.ai_base.agent_base.env_tool'),
            patch('topsailai.ai_base.agent_base.AgentNoCareResult', Exception),
            patch('topsailai.ai_base.agent_base.AgentNeedRefreshSession', Exception),
            patch('topsailai.ai_base.agent_base.DataAgentRefreshSession', MagicMock),
        ]
        for p in self.patches:
            p.start()

        # Configure env_tool mock
        import topsailai.ai_base.agent_base as module
        module.env_tool.is_use_tool_calls.return_value = True

    def tearDown(self):
        """Tear down test fixtures."""
        for p in reversed(self.patches):
            p.stop()

    def test_run_with_empty_user_input(self):
        """Test _run handles empty user input."""
        from topsailai.ai_base.agent_base import AgentRun

        agent = AgentRun(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        agent.available_tools = {}
        agent.messages = []  # Initialize messages
        agent.new_session = MagicMock()
        agent.llm_model.chat = MagicMock(return_value=(None, None))

        result = agent._run(self.step_call_mock, "")

        self.assertIsNone(result)

    def test_run_with_no_response_from_llm(self):
        """Test _run handles no response from LLM."""
        from topsailai.ai_base.agent_base import AgentRun

        agent = AgentRun(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        agent.available_tools = {}
        agent.messages = []  # Initialize messages
        agent.new_session = MagicMock()
        agent.llm_model.chat = MagicMock(return_value=(None, None))

        result = agent._run(self.step_call_mock, "test input")

        self.assertIsNone(result)

    def test_run_injects_runtime_messages_before_llm_chat(self):
        """Test _run calls _inject_runtime_messages before llm_model.chat."""
        from topsailai.ai_base.agent_base import AgentRun

        agent = AgentRun(
            system_prompt="You are a helpful assistant",
            tools={},
            agent_name="TestAgent"
        )
        agent.available_tools = {}
        agent.messages = []
        agent.new_session = MagicMock()

        call_order = []
        agent._inject_runtime_messages = MagicMock(side_effect=lambda: call_order.append("inject"))
        agent.llm_model.chat = MagicMock(
            return_value=(None, None),
            side_effect=lambda *args, **kwargs: (call_order.append("chat") or (None, None)),
        )

        agent._run(self.step_call_mock, "test input")

        self.assertEqual(call_order, ["inject", "chat"])

    @patch("topsailai.ai_base.llm_base.time.sleep")
    @patch("topsailai.ai_base.llm_base.thread_tool.is_main_thread", return_value=True)
    def test_request_retry_stays_inside_one_agent_run(
        self, mock_is_main_thread, mock_sleep
    ):
        """LLM request retries do not restart the Agent loop or rerun tools."""
        from topsailai.ai_base.agent_base import AgentRun
        from topsailai.ai_base.llm_retry import LLMRetryInteractionPolicy

        from topsailai.ai_base import agent_base as agent_base_module

        agent_base_module.env_tool.EnvReaderInstance.check_bool.return_value = False
        tool_schema = {"type": "function", "function": {"name": "tool"}}
        agent_base_module.get_tools_for_chat.return_value = {"tool": tool_schema}

        tool = MagicMock()
        agent = AgentRun(
            system_prompt="You are a helpful assistant",
            tools={"tool": tool},
            agent_name="TestAgent",
        )
        agent.available_tools = {"tool": tool}
        agent.messages = [{"role": "user", "content": "same request"}]
        agent.new_session = MagicMock()
        agent._inject_runtime_messages = MagicMock()
        agent._check_hard_interrupt = MagicMock()

        model = object.__new__(RealLLMModel)
        model.tokenStat = MagicMock(current_tokens=0, current_cached_tokens=0)
        model.call_llm_model = MagicMock(
            side_effect=[
                ValueError("temporary one"),
                ValueError("temporary two"),
                (MagicMock(), "recovered"),
            ]
        )
        model.call_llm_model_by_stream = MagicMock()
        response_object = MagicMock()
        response_object.tool_calls = None
        model._split_native_tool_call_response = MagicMock(
            return_value=(response_object, "recovered", 1, 1)
        )
        model._return_chat_response = MagicMock(
            return_value=(response_object, ["final"])
        )
        model.get_response_message = MagicMock(return_value=response_object)
        model.clear_pending_native_tool_call_responses = MagicMock()
        agent.llm_model = model

        from topsailai.ai_base.tool_call import StepCallBase

        class FinalStepCall(StepCallBase):
            """Return one final result without executing an available tool."""

            def __init__(self, retry_policy):
                super().__init__(llm_retry_policy=retry_policy)
                self.execution_count = 0

            def _execute(self, *args, **kwargs):
                self.execution_count += 1
                self.code = self.CODE_TASK_FINAL
                self.result = "done"

        step_call = FinalStepCall(LLMRetryInteractionPolicy())
        agent.add_assistant_message = MagicMock()
        original_run = agent.run
        agent.run = MagicMock(wraps=original_run)

        result = agent.run(step_call, "same request")

        self.assertEqual(result, "done")
        agent.run.assert_called_once_with(step_call, "same request")
        agent.new_session.assert_called_once()
        agent._inject_runtime_messages.assert_called_once_with()
        self.assertEqual(model.call_llm_model.call_count, 3)
        request_calls = model.call_llm_model.call_args_list
        request_messages = [call.args[0] for call in request_calls]
        request_tools = [call.kwargs["tools"] for call in request_calls]
        self.assertTrue(all(messages is agent.messages for messages in request_messages))
        self.assertTrue(all(tools is request_tools[0] for tools in request_tools))
        self.assertEqual(request_tools[0], [tool_schema])
        self.assertTrue(all(call.kwargs["tool_choice"] == "auto" for call in request_calls))
        model.call_llm_model_by_stream.assert_not_called()
        tool.assert_not_called()
        self.assertEqual(step_call.execution_count, 1)


if __name__ == '__main__':
    unittest.main()
