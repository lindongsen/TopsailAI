import unittest
from unittest.mock import MagicMock, patch

from topsailai.utils.thread_local_tool import (
    get_agent_runtime_input,
    rid_all_thread_vars,
)
from topsailai.workspace.agent.hooks.pre_run_input import (
    HOOKS,
    pre_run_set_agent_runtime_input,
)


class TestPreRunInputHook(unittest.TestCase):
    """Test cases for the pre_run_input hook."""

    def setUp(self):
        """Clear thread-local storage before each test."""
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local storage after each test."""
        rid_all_thread_vars()

    def test_hook_is_exported_with_pre_run_prefix(self):
        """The hook must be discoverable by get_hooks('pre_run')."""
        self.assertIn("pre_run_set_agent_runtime_input", HOOKS)
        self.assertIs(HOOKS["pre_run_set_agent_runtime_input"], pre_run_set_agent_runtime_input)

    def test_hook_registers_agent_runtime_input(self):
        """Calling the hook should register the agent-runtime input function."""
        self.assertIsNone(get_agent_runtime_input())

        mock_agent = MagicMock()
        pre_run_set_agent_runtime_input(mock_agent)

        input_func = get_agent_runtime_input()
        self.assertIsNotNone(input_func)
        self.assertEqual(input_func.__name__, "input_on_agent_runtime")

    @patch("topsailai.workspace.agent.hooks.pre_run_input.input_one_line")
    def test_wrapper_forwards_to_input_one_line_with_hook(self, mock_input_one_line):
        """The wrapper should pass through to input_one_line with the instruction hook."""
        mock_input_one_line.return_value = "user reply"
        mock_instruction = MagicMock()

        mock_agent = MagicMock()
        mock_agent.hook_instruction = mock_instruction
        pre_run_set_agent_runtime_input(mock_agent)

        input_func = get_agent_runtime_input()
        result = input_func("prompt text")

        self.assertEqual(result, "user reply")
        mock_input_one_line.assert_called_once_with(tips="prompt text", hook=mock_instruction)

    @patch("topsailai.workspace.agent.hooks.pre_run_input.input_one_line")
    def test_wrapper_uses_default_hook_when_none_provided(self, mock_input_one_line):
        """The wrapper should use the captured instruction when hook is not provided."""
        mock_input_one_line.return_value = "reply"
        mock_instruction = MagicMock()

        mock_agent = MagicMock()
        mock_agent.hook_instruction = mock_instruction
        pre_run_set_agent_runtime_input(mock_agent)

        input_func = get_agent_runtime_input()
        result = input_func(tips="enter value")

        self.assertEqual(result, "reply")
        mock_input_one_line.assert_called_once_with(tips="enter value", hook=mock_instruction)

    @patch("topsailai.workspace.agent.hooks.pre_run_input.input_one_line")
    def test_wrapper_preserves_explicit_hook(self, mock_input_one_line):
        """The wrapper should not override an explicitly provided hook."""
        mock_input_one_line.return_value = "reply"
        mock_instruction = MagicMock()
        other_hook = MagicMock()

        mock_agent = MagicMock()
        mock_agent.hook_instruction = mock_instruction
        pre_run_set_agent_runtime_input(mock_agent)

        input_func = get_agent_runtime_input()
        result = input_func("prompt", hook=other_hook)

        self.assertEqual(result, "reply")
        mock_input_one_line.assert_called_once_with(tips="prompt", hook=other_hook)


if __name__ == "__main__":
    unittest.main()
